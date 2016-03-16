import os
from importlib import import_module
import tornado.web
import tornado.httpserver
import tornado.ioloop
import tornado.options
import tornado.wsgi
import logging
import json

access_log = logging.getLogger("tornado.access")
app_log = logging.getLogger("tornado.application")
# gen_log = logging.getLogger("tornado.general")

SETTINGS = None


class Application(tornado.web.Application):

    def __init__(self, handlers, settings):
        tornado.web.Application.__init__(self, handlers, **settings)


class BaseHandler(tornado.web.RequestHandler):
    pass


def parse_log_file_option(option):
    if 'file://' in option:
        return {
            'type': 'file',
            'path': option[len('file://'):]
        }
    elif 'console' in option:
        return {
            'type': 'console',
        }
    elif 'rsyslog://' in option:
        return {
            'type': 'rsyslog',
            'uri': option[len('rsyslog://'):]
        }

    raise ValueError('Invalid logger option %s' % option)


def plugin_options():
    """Parse the plugin options from CLI as JSON string into dict and combine into plugin_config."""
    cli_opts = json.loads(tornado.options.options.plugin_opts)
    for plugin, values in cli_opts.iteritems():
        if plugin not in tornado.options.options.plugin_config:
            tornado.options.options.plugin_config[plugin] = cli_opts
        else:  # Merge and override plugin options in config file.
            for key, value in cli_opts[plugin].iteritems():
                tornado.options.options.plugin_config[plugin][key] = value


def parse_options():
    # General options CLI + Config
    tornado.options.define("config_file",
                           default=os.environ.get('MYUI_CONFIG', "/etc/myui.conf"),
                           help="webui port")
    tornado.options.define("app_title", default='My-UI')
    tornado.options.define("plugins", default="",
                           help="comma-separated list of plugins that should be loaded")
    tornado.options.define("plugin_opts",
                           default='{}',
                           help="JSON string of plugin specific options merged over "
                                "plugin_config dict")
    tornado.options.add_parse_callback(plugin_options)

    tornado.options.define("port", default="3000", help="webui port")
    tornado.options.define("login_url", default='/login')
    tornado.options.define("template_path", default=os.path.join(os.path.dirname(
        os.path.realpath(__file__)), 'templates'), help="templates directory name")

    tornado.options.define("static_path",
                           default=os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                                'static'),
                           help="static files dirctory name")
    tornado.options.define("cookie_secret", default='this is my secret.  you dont know it.')
    tornado.options.define("debug", default=True, help="enable tornado debug mode")

    # Config File Only Options
    tornado.options.parse_command_line(final=False)
    tornado.options.define("plugin_config",
                           default={},
                           help="Dictionary of config options")
    tornado.options.parse_config_file(tornado.options.options.config_file, final=True)


def gen_settings(mode='server'):
    """Generate settings dict from tornado.options.options"""
    try:
        tornado.options.options.port
        tornado.options.options.config_file
    except AttributeError:
        parse_options()

    return dict(template_path=tornado.options.options.template_path,
                login_url=tornado.options.options.login_url,
                static_path=tornado.options.options.static_path,
                cookie_secret=tornado.options.options.cookie_secret,
                debug=tornado.options.options.debug,
                plugin_config=tornado.options.options.plugin_config,
                app_title=tornado.options.options.app_title)


def init_models(plugin):
    """Initialize models with settings loaded from tornado settings.
        Typically called from inside the controller of a plugin except during model migrations
        and creations etc."""
    settings = gen_settings()

    # Generating list of models
    models = {}
    cursors = {}

    # Bootstrap plugin model settings if they exist
    try:
        plugin_model_opts = settings['plugin_config'][plugin]
    except KeyError:
        plugin_model_opts = None

    app_log.info('Loading models... ({0})'.format(plugin))
    list_of_models = generate_models(plugin)
    for model in list_of_models:
        models[model] = import_module('{0}.models.{1}'.format(plugin, model))
        try:
            # Initialize model
            cursors[model] = models[model].get_tables(plugin_model_opts)
        except Exception as e:
            app_log.error('Failed to load tables for %s.%s: %s' % (plugin, model, e.message))

    return cursors


def generate_models(plugin):
    models = import_module('{0}.models'.format(plugin))
    ret = [each for each in models.__all__]
    return ret


def generate_controllers(plugin):
    controllers = import_module('{0}.controllers'.format(plugin))
    ret = [each for each in controllers.__all__]
    return ret


def load_controllers():
    app_log.info('Loading controllers...')
    controllers = {}
    for plugin in tornado.options.options.plugins.split(','):
        list_of_controllers = generate_controllers(plugin)
        for controller in list_of_controllers:
            controllers[controller] = import_module(
                '{0}.controllers.{1}'.format(plugin, controller))
            app_log.info('Controller[{0}] loaded'.format(controller))
    return controllers


def create_models():
    """Run model init"""
    settings = gen_settings()
    for plugin in tornado.options.options.plugins.split(','):
        app_log.info('Running create on models in... (%s)' % plugin)
        for model in generate_models(plugin):
            modelObj = import_module('{0}.models.{1}'.format(plugin, model))
            modelObj.create(settings['plugin_config'][plugin])


def upgrade_models():
    """Run model upgrades"""
    settings = gen_settings()
    for plugin in tornado.options.options.plugins.split(','):
        app_log.info('Running upgrade on models in... (%s)' % plugin)
        for model in generate_models(plugin):
            modelObj = import_module('{0}.models.{1}'.format(plugin, model))
            modelObj.upgrade(settings['plugin_config'][plugin])


def application():
    settings = gen_settings()

    # Check to see if the plugin has uimodules
    try:
        settings['ui_modules'] = {'uimodules': import_module(
            '{0}.uimodules'.format(tornado.options.options.plugins))}
    except ImportError:
        pass

    controllers = load_controllers()

    # Build handlers
    handlers = []
    for controller in controllers:
        c = controllers[controller]
        c.Handler.logger = app_log
        if isinstance(c.params.route, basestring):
            handlers.append((c.params.route, c.Handler))
        else:
            for uri_string in c.params.route:
                handlers.append((uri_string, c.Handler))
    app_log.info('%s routes loaded for %s controllers' % (len(handlers), len(controllers)))
    return Application(handlers, settings)


def server():
    """Run dev server"""
    http_server = tornado.httpserver.HTTPServer(application())
    http_server.listen(tornado.options.options.port)
    app_log.info('Server up: listening on %s' % tornado.options.options.port)
    tornado.ioloop.IOLoop.instance().start()


def wsgiapp(*params):
    return tornado.wsgi.WSGIAdapter(application())(*params)
