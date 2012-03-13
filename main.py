#!/usr/bin/env python
# coding: utf-8
# Copyright 2011 Facebook, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


import os
import jinja2
# dummy config to enable registering django template filters
from google.appengine.ext.webapp.util import run_wsgi_app

os.environ['DJANGO_SETTINGS_MODULE'] = 'conf'


jinja_environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)))

from django.template.defaultfilters import register
from django.utils import simplejson as json
from functools import wraps
from google.appengine.api import urlfetch, taskqueue
from google.appengine.ext import db
from google.appengine.runtime import DeadlineExceededError
from random import randrange
from uuid import uuid4
from collections import namedtuple
import webapp2
import Cookie
import base64
import cgi
import conf
import datetime
import hashlib
import hmac
import logging
import time
import traceback
import urllib
import friendsFinder
from progressCache import ProgressCache


def htmlescape(text):
    """Escape text for use as HTML"""
    return cgi.escape(
        text, True).replace("'", '&#39;').encode('ascii', 'xmlcharrefreplace')


@register.filter(name='get_name')
def get_name(dic, index):
    """Django template filter to render name"""
    return dic[index].name


@register.filter(name='get_picture')
def get_picture(dic, index):
    """Django template filter to render picture"""
    return dic[index].picture


def select_random(lst, limit):
    """Select a limited set of random non Falsy values from a list"""
    final = []
    size = len(lst)
    while limit and size:
        index = randrange(min(limit, size))
        size = size - 1
        elem = lst[index]
        lst[index] = lst[size]
        if elem:
            limit = limit - 1
            final.append(elem)
    return final

_USER_FIELDS = 'name,email,picture,friends'
class User(db.Model):
    user_id = db.StringProperty(required=True)
    access_token = db.StringProperty(required=True)
    name = db.StringProperty(required=True)
    picture = db.StringProperty(required=True)
    email = db.StringProperty()
#    friends = db.StringListProperty()
    interestingFriends = db.StringListProperty()
#    dirty = db.BooleanProperty()

#    def refresh_data(self):
#        """Refresh this user's data using the Facebook Graph API"""
#        me = Facebook().api('/me',
#            {'fields': _USER_FIELDS, 'access_token': self.access_token})
#        self.dirty = False
#        self.name = me['name']
#        self.email = me.get('email')
#        self.picture = me['picture']
#        self.friends = [user['id'] for user in me['friends']['data']]
#        return self.put()

    def storeInterestingFriends(self, friends):
        self.interestingFriends = [str(couple) for couple in friends]
        self.put()


#class Run(db.Model):
#    user_id = db.StringProperty(required=True)
#    location = db.StringProperty(required=True)
#    distance = db.FloatProperty(required=True)
#    date = db.DateProperty(required=True)
#
#    @staticmethod
#    def find_by_user_ids(user_ids, limit=50):
#        if user_ids:
#            return Run.gql('WHERE user_id IN :1', user_ids).fetch(limit)
#        else:
#            return []
#
#    @property
#    def pretty_distance(self):
#        return '%.2f' % self.distance


class RunException(Exception):
    pass


class FacebookApiError(Exception):
    def __init__(self, result):
        self.result = result

    def __str__(self):
        return self.__class__.__name__ + ': ' + json.dumps(self.result)


class Facebook(object):
    """Wraps the Facebook specific logic"""
    def __init__(self, app_id=conf.FACEBOOK_APP_ID,
            app_secret=conf.FACEBOOK_APP_SECRET):
        self.app_id = app_id
        self.app_secret = app_secret
        self.user_id = None
        self.access_token = None
        self.signed_request = {}

    def api(self, path, params=None, method='GET', domain='graph'):
        """Make API calls"""
        if not params:
            params = {}
        params['method'] = method
        if 'access_token' not in params and self.access_token:
            params['access_token'] = self.access_token
        result = json.loads(urlfetch.fetch(
            url='https://' + domain + '.facebook.com' + path,
            payload=urllib.urlencode(params),
            method=urlfetch.POST,
            headers={
                'Content-Type': 'application/x-www-form-urlencoded'})
            .content)
        if isinstance(result, dict) and 'error' in result:
            raise FacebookApiError(result)
        return result

    def load_signed_request(self, signed_request):
        """Load the user state from a signed_request value"""
        try:
            sig, payload = signed_request.split('.', 1)
            sig = self.base64_url_decode(sig)
            data = json.loads(self.base64_url_decode(payload))

            expected_sig = hmac.new(
                self.app_secret, msg=payload, digestmod=hashlib.sha256).digest()

            # allow the signed_request to function for upto 1 day
            if sig == expected_sig and \
                    data['issued_at'] > (time.time() - 86400):
                self.signed_request = data
                self.user_id = data.get('user_id')
                self.access_token = data.get('oauth_token')
        except ValueError, ex:
            pass # ignore if can't split on dot

    @property
    def user_cookie(self):
        """Generate a signed_request value based on current state"""
        if not self.user_id:
            return
        payload = self.base64_url_encode(json.dumps({
            'user_id': self.user_id,
            'issued_at': str(int(time.time())),
        }))
        sig = self.base64_url_encode(hmac.new(
            self.app_secret, msg=payload, digestmod=hashlib.sha256).digest())
        return sig + '.' + payload

    @staticmethod
    def base64_url_decode(data):
        data = data.encode('ascii')
        data += '=' * (4 - (len(data) % 4))
        return base64.urlsafe_b64decode(data)

    @staticmethod
    def base64_url_encode(data):
        return base64.urlsafe_b64encode(data).rstrip('=')


class CsrfException(Exception):
    pass


class BaseHandler(webapp2.RequestHandler):
    facebook = None
    userID = None
    user = None
    csrf_protect = True

    def initialize(self, request, response):
        """General initialization for every request"""
        super(BaseHandler, self).initialize(request, response)

        try:
            self.init_facebook()
            self.init_csrf()
            self.response.headers['P3P'] = 'CP=HONK'  # iframe cookies in IE
        except Exception, ex:
            self.log_exception(ex)
            raise

    def handle_exception(self, ex, debug_mode):
        """Invoked for unhandled exceptions by webapp"""
        self.log_exception(ex)
        self.render('error',
            trace=traceback.format_exc(), debug_mode=debug_mode)

    def log_exception(self, ex):
        """Internal logging handler to reduce some App Engine noise in errors"""
        msg = ((str(ex) or ex.__class__.__name__) +
                ': \n' + traceback.format_exc())
        if isinstance(ex, urlfetch.DownloadError) or \
           isinstance(ex, DeadlineExceededError) or \
           isinstance(ex, CsrfException) or \
           isinstance(ex, taskqueue.TransientError):
            logging.warn(msg)
        else:
            logging.error(msg)

    def set_cookie(self, name, value, expires=None):
        """Set a cookie"""
        if value is None:
            value = 'deleted'
            expires = datetime.timedelta(minutes=-50000)
        jar = Cookie.SimpleCookie()
        jar[name] = value
        jar[name]['path'] = '/'
        if expires:
            if isinstance(expires, datetime.timedelta):
                expires = datetime.datetime.now() + expires
            if isinstance(expires, datetime.datetime):
                expires = expires.strftime('%a, %d %b %Y %H:%M:%S')
            jar[name]['expires'] = expires
        self.response.headers.add_header(*jar.output().split(': ', 1))

    def render(self, name, **data):
        """Render a template"""
        if not data:
            data = {}
        data['js_conf'] = json.dumps({
            'appId': conf.FACEBOOK_APP_ID,
            'canvasName': conf.FACEBOOK_CANVAS_NAME,
            'userIdOnServer': self.user.user_id if self.user else None,
        })
        data['logged_in_user'] = self.user
        data['message'] = self.get_message()
        data['csrf_token'] = self.csrf_token
        data['canvas_name'] = conf.FACEBOOK_CANVAS_NAME

#        template = jinja_environment.get_template(os.path.join(os.path.dirname(__file__), 'templates', name + '.html'))
        template = jinja_environment.get_template(os.path.join('templates', name + '.html'))
        self.response.write(template.render(data))

    def init_facebook(self):
        """Sets up the request specific Facebook and User instance"""
        facebook = Facebook()
        user = None

        # initial facebook request comes in as a POST with a signed_request
        if 'signed_request' in self.request.POST:
            facebook.load_signed_request(self.request.get('signed_request'))
            # we reset the method to GET because a request from facebook with a
            # signed_request uses POST for security reasons, despite it
            # actually being a GET. in webapp causes loss of request.POST data.
            self.request.method = 'GET'
            self.set_cookie(
                '', facebook.user_cookie, datetime.timedelta(minutes=1440))
        elif '' in self.request.cookies:
            facebook.load_signed_request(self.request.cookies.get(''))

        # try to load or create a user object
        if facebook.user_id:
            self.userID = facebook.user_id
            user = User.get_by_key_name(facebook.user_id)
            if user:
                # update stored access_token
                if facebook.access_token and \
                        facebook.access_token != user.access_token:
                    user.access_token = facebook.access_token
                    user.put()
                # refresh data if we failed in doing so after a realtime ping
#                if user.dirty:
#                    user.refresh_data()
                # restore stored access_token if necessary
                if not facebook.access_token:
                    facebook.access_token = user.access_token

            if not user and facebook.access_token:
                me = facebook.api('/me', {'fields': _USER_FIELDS})
                try:
#                    friends = [user['id'] for user in me['friends']['data']]
                    user = User(key_name=facebook.user_id,
                        user_id=facebook.user_id,
                        access_token=facebook.access_token, name=me['name'],
                        email=me.get('email'), picture=me['picture'])
                    user.put()
                except KeyError, ex:
                    pass # ignore if can't get the minimum fields

        self.facebook = facebook
        self.user = user

    def init_csrf(self):
        """Issue and handle CSRF token as necessary"""
        self.csrf_token = self.request.cookies.get('c')
        if not self.csrf_token:
            self.csrf_token = str(uuid4())[:8]
            self.set_cookie('c', self.csrf_token)
        if self.request.method == 'POST' and self.csrf_protect and \
                self.csrf_token != self.request.POST.get('_csrf_token'):
            raise CsrfException('Missing or invalid CSRF token.')

    def set_message(self, **obj):
        """Simple message support"""
        self.set_cookie('m', base64.b64encode(json.dumps(obj)) if obj else None)

    def get_message(self):
        """Get and clear the current message"""
        message = self.request.cookies.get('m')
        if message:
            self.set_message()  # clear the current cookie
            return json.loads(base64.b64decode(message))


def user_required(fn):
    """Decorator to ensure a user is present"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        handler = args[0]
        if handler.user:
            return fn(*args, **kwargs)
        handler.redirect('/')
    return wrapper


class RecentRunsHandler(BaseHandler):
    """Show recent runs for the user and friends"""
    NUM_OF_PAIRS = 20
    def get(self):
        if self.user:
            if not self.user.interestingFriends:
                if ProgressCache.get(self.userID, 'isRunning'):
                    logging.info('Algorithm is already running')
                else:
                    ProgressCache.set(self.userID, 'isRunning', True)
                    logging.info('Starting algorithm')
                    taskqueue.add(url = '/calc-friends', method = 'GET', params =
                        {'access_token': self.user.access_token,
                        'user_id': self.user.user_id})
                self.render('runs', interestingFriends = None, userID = self.userID)
            else:
                logging.info('Retrieving interesting friends from DB')
                interestingFriendsList = eval(str(self.user.interestingFriends))
                Couple = namedtuple('Couple', 'firstName firstID secondName secondID')
                interestingFriends = [eval(couple) for couple in interestingFriendsList]
                firstFriends = interestingFriends[: self.NUM_OF_PAIRS / 2]
                lastFriends = interestingFriends[self.NUM_OF_PAIRS / 2: self.NUM_OF_PAIRS]

#                if ProgressCache.get(self.userID, 'isRunning'):
#                    self.render('runs', interestingFriends = None, userID = self.userID)
#                else:
                self.render('runs', interestingFriends = interestingFriends, firstFriends = firstFriends, lastFriends = lastFriends)

        else:
            self.render('welcome')

class CacheHandler(BaseHandler):
    """Used to cache the algorithm progress"""

    def cleanKeys(self, dict):
        newDict = {}
        for key, value in dict.items():
            _, progress = key.split('__')
            newDict[progress] = value

        return newDict

    def get(self):
        self.response.out.write(json.dumps(self.cleanKeys(ProgressCache.getMulti(
            self.request.get('userID'),
            ['fetch_progress', 'graph_progress', 'edges_progress', 'ratio_progress', 'isRunning']))))
#        timeFraction = time.time() % 25
#        fetch = min(timeFraction / 5, 1)
#        graph = min(max(timeFraction - 5, 0) / 5, 1)
#        edges = min(max(timeFraction - 10, 0) / 5, 1)
#        ratio = min(max(timeFraction - 15, 0) / 5, 1)
#        isRunning = ratio < 1
#        ProgressCache.setMulti(self.request.get('userID'), {'fetch_progress': fetch, 'graph_progress': graph, 'edges_progress': edges, 'ratio_progress': ratio, 'isRunning': isRunning})
#        self.response.out.write(json.dumps(self.cleanKeys(ProgressCache.getMulti(self.request.get('userID'), ['fetch_progress', 'graph_progress', 'edges_progress', 'ratio_progress', 'isRunning']))))

class FlushHandler(BaseHandler):
    """Used to cache the algorithm progress"""

    def get(self):
        ProgressCache.flush()

class CalcFriendsHandler(BaseHandler):
    """Used to calculate the interesting friends graph asynchronously"""

    def get(self):
        logging.info('Calculating interesting friends')
        ProgressCache.setMulti(self.request.get('user_id'), {'fetch_progress': 0, 'graph_progress': 0, 'edges_progress': 0, 'ratio_progress': 0})
        try:
            finder = friendsFinder.FriendsFinder(self.request.get('access_token'), self.request.get('user_id'))
            interestingFriends = finder.getInterestingFriends()
            user = User.get_by_key_name(self.request.get('user_id'))
            user.storeInterestingFriends(interestingFriends[: 20])
        except DeadlineExceededError:
            self.response.clear()
            self.response.set_status(500)
            self.response.out.write("You have too many friends...")
        finally:
            # reset progress counters
            ProgressCache.set(self.request.get('user_id'), 'isRunning', False)

routes = [
    (r'/', RecentRunsHandler),
    (r'/cache', CacheHandler),
    (r'/flush', FlushHandler),
    (r'/calc-friends', CalcFriendsHandler)
]
#    application = webapp2.WSGIApplication(routes, debug=os.environ.get('SERVER_SOFTWARE', '').startswith('Dev'))
application = webapp2.WSGIApplication(routes)
