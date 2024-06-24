import ckan.plugins as p
import ckan.plugins.toolkit as tk


@tk.blanket.actions
@tk.blanket.auth_functions
@tk.blanket.blueprints
@tk.blanket.validators
class DatavicHomePlugin(p.SingletonPlugin):
    p.implements(p.IConfigurer)

    # IConfigurer
    def update_config(self, config_):
        tk.add_template_directory(config_, "templates")
        tk.add_resource("assets", "vic_home")
