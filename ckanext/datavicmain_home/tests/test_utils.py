from ckanext.datavicmain_home.utils import get_config_schema


class TestGetConfigSchema:
    def test_get_config_schema(self):
        schema = get_config_schema()

        assert schema
        assert isinstance(schema, dict)
