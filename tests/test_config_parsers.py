# tests/test_config_parsers.py
"""
Tests for configuration file parsers.
"""

import pytest
from pathlib import Path
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from src.processors.config_parsers.base import BaseConfigParser
from src.processors.config_parsers.nginx_proxy import NPMConfigParser
from src.processors.config_parsers.registry import ParserRegistry


class TestNPMConfigParser:
    """Tests for NPM (Nginx Proxy Manager) configuration parser"""

    @pytest.fixture
    def parser(self):
        """Create NPM parser instance"""
        return NPMConfigParser()

    @pytest.fixture
    def sample_npm_config(self):
        """Sample NPM configuration content"""
        return """# ------------------------------------------------------------
# registry-ui.maxseiner.casa
# ------------------------------------------------------------

map $scheme $hsts_header {
    https   "max-age=63072000; preload";
}

server {
  set $forward_scheme http;
  set $server         "10.20.0.162";
  set $port           8080;

  listen 80;
  listen [::]:80;

  listen 443 ssl;
  listen [::]:443 ssl;

  server_name registry-ui.maxseiner.casa;

  http2 on;

  # Let's Encrypt SSL
  include conf.d/include/letsencrypt-acme-challenge.conf;
  include conf.d/include/ssl-cache.conf;
  include conf.d/include/ssl-ciphers.conf;
  ssl_certificate /etc/letsencrypt/live/npm-9/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/npm-9/privkey.pem;

  # Asset Caching
  include conf.d/include/assets.conf;

  # Block Exploits
  include conf.d/include/block-exploits.conf;

  # HSTS
  add_header Strict-Transport-Security $hsts_header always;

  location / {
    proxy_pass http://10.20.0.162:8080;
  }
}
"""

    def test_can_process_npm_config(self, parser):
        """Test that parser recognizes NPM configs"""
        assert parser.can_process('nginx-proxy-manager', 'proxy') is True
        assert parser.can_process('apache', 'proxy') is False
        assert parser.can_process('nginx-proxy-manager', 'monitoring') is False

    def test_parse_npm_config(self, parser, sample_npm_config):
        """Test parsing NPM configuration"""
        result = parser.parse(sample_npm_config, 'test.conf')

        assert result is not None
        assert result['server_name'] == 'registry-ui.maxseiner.casa'
        assert result['upstream'] == '10.20.0.162:8080'
        assert result['upstream_ip'] == '10.20.0.162'
        assert result['upstream_port'] == 8080
        assert 80 in result['listen_ports']
        assert 443 in result['listen_ports']
        assert result['ssl_enabled'] is True
        assert result['http2_enabled'] is True
        assert result['forward_scheme'] == 'http'
        assert '/etc/letsencrypt/live/npm-9/fullchain.pem' in result['ssl_certificate']
        assert '/etc/letsencrypt/live/npm-9/privkey.pem' in result['ssl_certificate_key']

    def test_extract_search_terms(self, parser, sample_npm_config):
        """Test search term extraction"""
        parsed = parser.parse(sample_npm_config, 'test.conf')
        terms = parser.extract_search_terms(parsed)

        assert 'registry-ui.maxseiner.casa' in terms
        assert '10.20.0.162:8080' in terms
        assert '10.20.0.162' in terms
        assert 'ssl-enabled' in terms
        assert 'https' in terms
        assert 'http2' in terms

    def test_parse_with_aliases(self, parser):
        """Test parsing config with server name aliases"""
        config_with_aliases = """
server {
  server_name example.com www.example.com api.example.com;
  set $server "192.168.1.100";
  set $port 3000;
  listen 80;
}
"""
        result = parser.parse(config_with_aliases, 'test.conf')

        assert result is not None
        assert result['server_name'] == 'example.com'
        assert 'www.example.com' in result['server_name_aliases']
        assert 'api.example.com' in result['server_name_aliases']

    def test_parse_without_ssl(self, parser):
        """Test parsing config without SSL"""
        config_no_ssl = """
server {
  server_name http-only.example.com;
  set $server "10.0.0.1";
  set $port 8080;
  listen 80;
}
"""
        result = parser.parse(config_no_ssl, 'test.conf')

        assert result is not None
        assert result['ssl_enabled'] is False
        assert result['ssl_certificate'] is None
        assert result['ssl_certificate_key'] is None

    def test_parse_invalid_config(self, parser):
        """Test parsing invalid or empty config"""
        result = parser.parse("", 'empty.conf')
        assert result is None

        result = parser.parse("random text without server blocks", 'invalid.conf')
        assert result is None


class TestParserRegistry:
    """Tests for parser registry"""

    @pytest.fixture
    def registry(self):
        """Create parser registry instance"""
        return ParserRegistry()

    def test_get_npm_parser(self, registry):
        """Test getting NPM parser from registry"""
        parser = registry.get_parser('nginx-proxy-manager', 'proxy')
        assert parser is not None
        assert isinstance(parser, NPMConfigParser)

    def test_get_nonexistent_parser(self, registry):
        """Test getting parser that doesn't exist"""
        parser = registry.get_parser('unknown-service', 'unknown-type')
        assert parser is None

    def test_list_parsers(self, registry):
        """Test listing all registered parsers"""
        parsers = registry.list_parsers()
        assert 'NPMConfigParser' in parsers
        assert len(parsers) >= 1


class TestBaseConfigParser:
    """Tests for base parser interface"""

    def test_base_parser_is_abstract(self):
        """Test that BaseConfigParser cannot be instantiated directly"""
        with pytest.raises(TypeError):
            BaseConfigParser()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
