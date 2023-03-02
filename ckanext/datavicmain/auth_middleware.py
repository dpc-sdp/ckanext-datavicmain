import logging
import ckan.model as model
import ckan.plugins.toolkit as toolkit

from ckan.lib import base

config = toolkit.config
request = toolkit.request
log = logging.getLogger(__name__)

#   The code in this class was copied (& adjusted) from the CKAN 2.2 repository


class AuthMiddleware(object):
    def __init__(self, app, app_conf):
        self.app = app

    def __call__(self, environ, start_response):
        # if logged in via browser cookies or API key, all pages accessible
        if 'repoze.who.identity' in environ or self._get_user_for_apikey(environ) or not self._is_iar():
            return self.app(environ, start_response)
        else:
            # otherwise only login/reset and front pages are accessible
            if (environ['PATH_INFO'] == '/'
                or environ['PATH_INFO'] == '/user/login'
                or environ['PATH_INFO'] == '/user/_logout'
                or '/user/reset' in environ['PATH_INFO']
                or environ['PATH_INFO'] == '/user/logged_out'
                or environ['PATH_INFO'] == '/user/logged_in'
                or environ['PATH_INFO'] == '/user/logged_out_redirect'
                or environ['PATH_INFO'] == '/user/register'
                or environ['PATH_INFO'] == '/favicon.ico'
                or environ['PATH_INFO'].startswith('/api')
                or environ['PATH_INFO'].startswith('/base')
                or environ['PATH_INFO'].startswith('/webassets')
                or environ['PATH_INFO'].startswith('/images')
                or environ['PATH_INFO'].startswith('/css')
                or environ['PATH_INFO'].startswith('/js')
                or environ['PATH_INFO'].startswith('/_debug')
                or environ['PATH_INFO'].startswith('/uploads')
                or environ['PATH_INFO'].startswith('/fonts')
                or environ['PATH_INFO'].startswith('/assets')
                    or environ['PATH_INFO'].endswith('svg')):
                return self.app(environ, start_response)
            else:
                log.debug(f"Unauthorized page accessed: {environ['PATH_INFO']}")
                # Status code needs to be 3xx (redirection) for Location header to be used
                status = "302 Unauthorized"
                location = '/user/login'
                headers = [('Location', location),
                           ('Content-Length', '0')]
                log.debug(f"Redirecting to: {location}")
                start_response(status, headers)
                # Return now as we want to end the request
                return []

    def _get_user_for_apikey(self, environ):
        # Adapted from https://github.com/ckan/ckan/blob/625b51cdb0f1697add59c7e3faf723a48c8e04fd/ckan/lib/base.py#L396
        apikey_header_name = config.get(base.APIKEY_HEADER_NAME_KEY,
                                        base.APIKEY_HEADER_NAME_DEFAULT)
        apikey = environ.get(apikey_header_name, '')
        if not apikey:
            # For misunderstanding old documentation (now fixed).
            apikey = environ.get('HTTP_AUTHORIZATION', '')
        if not apikey:
            apikey = environ.get('Authorization', '')
            # Forget HTTP Auth credentials (they have spaces).
            if ' ' in apikey:
                apikey = ''
        if not apikey:
            return None
        apikey = str(apikey)
        # check if API key is valid by comparing against keys of registered users
        query = model.Session.query(model.User)
        user = query.filter_by(apikey=apikey).first()
        return user

    def _is_iar(self):
        return toolkit.asbool(config.get('ckan.iar', False))
