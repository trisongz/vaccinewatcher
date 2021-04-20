import sys
import time
import json
import elemental
import threading
import requests
from seleniumwire import webdriver
from subprocess import check_output
from dataclasses import dataclass
from datetime import datetime
import argparse
import gc
from . import get_logger

logger = get_logger()

_watcher_lock = threading.Lock()
_watcher = None

def run_command(cmd):
    out = check_output(cmd, shell=True)
    if isinstance(out, bytes):
        out = out.decode('utf8')
    return out.strip()

def create_timestamp():
    return datetime.now().strftime('%m-%d-%Y %H:%M:%S')

class Browser:
    def __init__(self):
        self.chrome_options = webdriver.ChromeOptions()
        self.chrome_options.add_argument("--disable-gpu")
        self.chrome_options.add_argument("--disable-software-rasterizer")
        self.chrome_options.add_argument("--headless")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("--window-size=1920x1080")
        self.chrome_options.add_argument("--disable-setuid-sandbox")
        self.chrome_options.add_argument("--no-sandbox")
        self.selenium_wire_options = {
            'exclude_hosts': ['google-analytics.com', 'facebook.com', 'youtube.com', 'adservice.google.com', 'insight.adsrvr.org']
        }
        self.exec_path = run_command('which chromedriver')
        self._driver = None
        self._browser = None
        self._calls = 0
    
    def should_reset(self):
        if self._calls > 10:
            self._reset()
            self._calls = 0
        self._calls += 1

    def _reset(self):
        self._create_driver()
        self._create_browser()
    
    def _create_driver(self):
        if self._driver:
            self.close()
        self._driver = webdriver.Chrome(options=self.chrome_options, seleniumwire_options=self.selenium_wire_options, executable_path=self.exec_path)
    
    def _create_browser(self):
        if self._browser:
            return
        if not self._driver:
            self._create_driver()
        self._browser = elemental.Browser(self._driver)

    @property
    def driver(self):
        if not self._driver:
            self._create_driver()
        return self._driver
    
    @property
    def browser(self):
        if not self._browser:
            self._create_browser()
        return self._browser

    def close(self):
        self._driver.close()
        self._driver.quit()
        self._driver = None
        self._browser = None
        gc.collect()
    

@dataclass
class Config:
    city: str = 'Houston'
    state: str = 'Texas'
    state_abbr: str = 'TX'
    zipcode: str = '77056'

_wg_steps = [
    'https://www.walgreens.com/',
    'https://www.walgreens.com/findcare/vaccination/covid-19?ban=covid_scheduler_brandstory_main_March2021',
]
_avail_links = {
    'cvs': 'https://www.cvs.com/immunizations/covid-19-vaccine?icid=cvs-home-hero1-link2-coronavirus-vaccine',
    'wg': 'https://www.walgreens.com/findcare/vaccination/covid-19?ban=covid_scheduler_brandstory_main_March2021'
}

class VaccineWatcher:
    def __init__(self, config, freq_secs=600, hook=None, check_walgreens=True, check_cvs=True, send_data=True, always_send=False, verbose=False):
        self.config = Config(**config)
        self.freq = freq_secs
        self.send_data = send_data
        self.always_send = always_send
        self.hook = hook
        self.verbose = verbose
        self._last_status = {'walgreens': {'available': False, 'data': None, 'timestamp': None}, 'cvs': {'available': False, 'data': None, 'timestamp': None}}
        self._check_wg = check_walgreens
        self._check_cvs = check_cvs
        self.api = Browser()
        self.browser = self.api.browser
        self.alive = True
        self.dactive = False
        logger.log(f'Initialized VaccineWatcher with {self.config}. Will Check every {self.freq} secs. Walgreens: {self._check_wg}. CVS: {self._check_cvs}\nCall .run() to start daemon')
    
    def _wg_parser(self, resp):
        data = json.loads(resp.body.decode('utf-8'))
        self._last_status['walgreens']['data'] = data
        if data.get('appointmentsAvailable') and data['appointmentsAvailable']:
            msg = f'Walgreens has Available Appointments: {data["availabilityGroups"]} for Next {data["days"]} in {data["zipCode"]}, {data["stateCode"]} in {data["radius"]} mile radius'
            msg += f'\nPlease Visit: {_avail_links["wg"]} to schedule.'
            self._call_hook(msg)
            logger.log(msg)
            return True
        if self.verbose:
            msg = f'Result for Walgreens: {data}'
            logger.log(msg)
        return False
    
    def check_wg(self):
        self.browser.visit(_wg_steps[0])
        time.sleep(5)
        self.browser.visit(_wg_steps[1])
        time.sleep(5)
        self.browser.get_element(partial_link_text="Schedule new appointment").click()
        time.sleep(3)
        self.browser.get_input(id="inputLocation").fill(f'{self.config.city} {self.config.state} {self.config.zipcode}')
        self.browser.get_button(text="Search").click()
        time.sleep(1)
        reqs = self.browser.selenium_webdriver.requests
        for r in reqs:
            if r.response:
                if '/hcschedulersvc/svc/v1/immunizationLocations/availability' in r.url:
                    return self._wg_parser(r.response)
        return None

    def _cvs_parser(self, resp):
        data = json.loads(resp.body.decode('utf-8'))['responsePayloadData']['data'][self.config.state_abbr]
        for item in data:
            if item['city'] == self.config.city.upper():
                self._last_status['cvs']['data'] = item
                if item['status'] == 'Available':
                    msg = f'CVS has Available Appointments in {item["city"]}, {item["state"]}'
                    msg += f'\nPlease Visit: {_avail_links["cvs"]} to schedule.'
                    self._call_hook(msg)
                    logger.log(msg)
                    return True
                if self.verbose:
                    msg = f'Results for CVS: {item}'
                    logger.log(msg)
                return False 

    def check_cvs(self):
        self.browser.visit('https://www.cvs.com/')
        time.sleep(1)
        self.browser.get_element(partial_link_text="Schedule a COVID-19 vaccine").click()
        self.browser.get_element(partial_link_text=self.config.state).click()
        reqs = self.browser.selenium_webdriver.requests
        for r in reqs:
            if r.response:
                if 'https://www.cvs.com/immunizations/covid-19-vaccine.vaccine-status' in r.url:
                    return self._cvs_parser(r.response)
        return None

    def run(self):
        if not self.dactive:
            t = threading.Thread(target=self._daemon, daemon=True)
            t.start()
    
    def last_check(self):
        return self._last_status
    
    def _call_hook(self, msg=None):
        if not self.hook:
            return
        if not msg and not self.send_data:
            return
        if msg and self.send_data:
            self.hook(message=msg, data=self.last_check())
        elif msg:
            self.hook(message=msg)
        elif always_send:
            self.hook(message=None, data=self.last_check())
                
    
    def _daemon(self):
        self.dactive = True
        print(f'Vaccine Watcher Active')
        while self.alive:
            if self._check_cvs:
                self._last_status['cvs']['available'] = self.check_cvs()
                self._last_status['cvs']['timestamp'] = create_timestamp()
            if self._check_wg:
                self._last_status['walgreens']['available'] = self.check_wg()
                self._last_status['walgreens']['timestamp'] = create_timestamp()
            self._call_hook()
            self.api.should_reset()
            time.sleep(self.freq)

    def __call__(self, check_walgreens=True, check_cvs=True):
        res = {}
        if check_walgreens:
            res['walgreens'] = self.check_wg()
        if check_cvs:
            res['cvs'] = self.check_cvs()
        return res

    def __enter__(self):
        return self
    
    def close(self):
        self.alive = False
        self.api.close
        msg = 'Vaccine Watcher is exiting'
        self._call_hook(msg)
        logger.log(msg)


    def __exit__(self, *_):
        self.close()
        

def configure_watcher(**config):
    global _watcher
    with _watcher_lock:
        if _watcher:
            return
        _watcher = VaccineWatcher(**config)


def get_vaccine_watcher(**config):
    configure_watcher(**config)
    return _watcher


class ZapierWebhook:
    def __init__(self, url):
        self.url = url
        self.s = requests.Session()
        logger.log(f'Initialized Zapier Webhook at {self.url}')
    
    def __call__(self, message=None, data=None):
        if not message or data:
            return
        params = {}
        if message:
            params['message'] = message
        if data:
            params.update(data)
        params['timestamp'] = create_timestamp()
        r = self.s.post(self.url, json=params)
        if r.status_code == 200:
            logger.log(f'Successfully sent to Zapier Webhook: {params}')
        else:
            logger.log(f'Potential Error sending to Zapier Webhook')


def cli():
    parser = argparse.ArgumentParser(description='Vaccine Watcher CLI')
    parser.add_argument('--city', dest='city', type=str, default="Houston", help='Full name of your City.')
    parser.add_argument('--state', dest='state', type=str, default="Texas", help='Full name of your State.')
    parser.add_argument('--abbr', dest='state_abbr', type=str, default="TX", help='State Abbreviation')
    parser.add_argument('--zip', dest='zipcode', type=str, default="77056", help='Your nearest Zipcode')

    parser.add_argument('--freq', dest='freq', type=int, default=600, help='Seconds between refreshes')

    parser.add_argument('--zapier', dest='zapierhook', type=str, default=None, help='A Zapier Webhook URL to Send Messages/Notifications')

    parser.add_argument('--no-cvs', dest='cvs', default=True, action='store_false', help='Disable CVS Search.')
    parser.add_argument('--no-wg', dest='wg', default=True, action='store_false', help='Disable Walgreens Search.')
    parser.add_argument('--verbose', dest='verbose', default=False, action='store_true', help='Enable verbosity. Will log results regardless of status')
    args = parser.parse_args()
    params = {'city': args.city.capitalize(), 'state': args.state.capitalize(), 'state_abbr': args.state_abbr.upper(), 'zipcode': args.zipcode}
    hook = None
    if args.zapierhook:
        hook = ZapierWebhook(args.zapierhook)
    watcher = get_vaccine_watcher(config=params, freq_secs=args.freq, hook=hook, check_walgreens=args.wg, check_cvs=args.cvs, verbose=args.verbose)
    watcher.run()
    while True:
        try:
            time.sleep(60)
        
        except KeyboardInterrupt:
            logger.info('Exiting due to Keyboard Interrupt')
            watcher.close()
            sys.exit()
        
        except Exception as e:
            watcher.close()
            logger.info(f'Exiting Due to Error: {str(e)}')
            sys.exit()


if __name__ == '__main__':
    cli()

