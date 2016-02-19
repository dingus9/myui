import tornado.web
from myui import BaseHandler


class params:
    route = '/example'
    pass


class Handler(BaseHandler):
    @tornado.web.removeslash
    def get(self):
        self.render('example.html')
