# DataVic Main

This CKAN extension contains a number of general functions specific to the DataVic IAR and ODP instances.

## Access Control Middleware

This extension includes a middleware implementation to restrict access to the CKAN instance for non-logged in users.

This can be controlled by setting the `ckan.iar` property in the respective config `.ini` file to True or False.

        ckan.iar = True

