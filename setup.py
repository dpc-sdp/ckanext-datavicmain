from setuptools import find_packages, setup

version = "1.0"

setup(
    name="datavicmain",
    version=version,
    description="DataVic Main extension",
    long_description="""\
    """,
    classifiers=[],  # Get strings from http://pypi.python.org/pypi?%3Aaction=list_classifiers
    keywords="",
    author="Salsa Digital",
    author_email="info@salsadigital.com.au",
    url="",
    license="",
    packages=find_packages(exclude=["ez_setup", "examples", "tests"]),
    namespace_packages=["ckanext", "ckanext.datavicmain"],
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        # -*- Extra requirements: -*-
        "jsonpickle",
        "cryptography!=39.0.0",  # this version doesn't work with urllib3 required by CKAN core
        "ckanapi",
    ],
    entry_points="""
        [ckan.plugins]
        datavicmain_dataset = ckanext.datavicmain.plugins:DatasetForm
        datavicmain_home = ckanext.datavicmain_home.plugins:DatavicHomePlugin

        [fanstatic.libraries]
    """,
)
