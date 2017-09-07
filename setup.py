from setuptools import setup, find_packages
import sys, os

version = '0.9'

setup(
	name='ckanext-datavicmain',
	version=version,
	description="DataVic Main extension",
	long_description="""\
	""",
	classifiers=[], # Get strings from http://pypi.python.org/pypi?%3Aaction=list_classifiers
	keywords='',
	author='Salsa Digital',
	author_email='info@salsadigital.com.au',
	url='',
	license='',
	packages=find_packages(exclude=['ez_setup', 'examples', 'tests']),
	namespace_packages=['ckanext', 'ckanext.datavicmain'],
	include_package_data=True,
	zip_safe=False,
	install_requires=[
		# -*- Extra requirements: -*-
        "jsonpickle",
	],
	entry_points=\
	"""
        [ckan.plugins]

        datavicmain_dataset = ckanext.datavicmain.plugins:DatasetForm

        [fanstatic.libraries]

	""",
)
