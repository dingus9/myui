import tornado.web
from myui import BaseHandler


class params:
    route = '/'
    pass


class Handler(BaseHandler):
    @tornado.web.removeslash
    def get(self):
        self.write('home')
