# DataVic Main

This CKAN extension contains a number of general functions specific to the DataVic IAR and ODP instances.

## Access Control Middleware

This extension includes a middleware implementation to restrict access to the CKAN instance for non-logged in users.

This can be controlled by setting the `ckan.iar` property in the respective config `.ini` file to True or False.

        ckan.iar = True

The implementation was copied from the existing CKAN 2.2 code here:

https://github.com/salsadigitalauorg/datavic_ckan_2.2/blob/develop/iar/src/ckanext-datavic/ckanext/datavic/plugin.py

Minor adjustments were made to incorporate it into this extension.
