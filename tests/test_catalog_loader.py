"""Tests for the catalog module's load/get logic."""

import os
from unittest.mock import patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import yaml

from app import catalog


def _make_service_yaml(
    slug="test-svc",
    name="Test Service",
    category="bandwidth",
    status="active",
    description="A test service",
    docker=None,
):
    data = {
        "name": name,
        "slug": slug,
        "category": category,
        "status": status,
        "description": description,
        "docker": docker or {"image": "test/image:latest"},
    }
    return yaml.dump(data)


class TestLoadFromDisk:
    def test_loads_yml_files(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "testsvc.yml").write_text(_make_service_yaml("testsvc"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            services = catalog._load_from_disk()
        assert len(services) == 1
        assert services[0]["slug"] == "testsvc"

    def test_skips_underscore_files(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "_schema.yml").write_text(_make_service_yaml("schema"))
        (svc_dir / "real.yml").write_text(_make_service_yaml("real"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            services = catalog._load_from_disk()
        assert len(services) == 1
        assert services[0]["slug"] == "real"

    def test_skips_invalid_yaml(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "bad.yml").write_text("{{{{invalid yaml")
        (svc_dir / "good.yml").write_text(_make_service_yaml("good"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            services = catalog._load_from_disk()
        assert len(services) == 1

    def test_skips_non_dict_yaml(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "list.yml").write_text("- item1\n- item2\n")
        (svc_dir / "good.yml").write_text(_make_service_yaml("good"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            services = catalog._load_from_disk()
        assert len(services) == 1

    def test_skips_missing_required_fields(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "incomplete.yml").write_text(yaml.dump({"name": "Only Name"}))
        (svc_dir / "good.yml").write_text(_make_service_yaml("good"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            services = catalog._load_from_disk()
        assert len(services) == 1

    def test_missing_services_dir(self, tmp_path):
        with patch.object(catalog, "SERVICES_DIR", tmp_path / "nonexistent"):
            services = catalog._load_from_disk()
        assert services == []

    def test_loads_yaml_extension(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "svc.yaml").write_text(_make_service_yaml("svc"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            services = catalog._load_from_disk()
        assert len(services) == 1


class TestCatalogCache:
    def test_load_services_populates_cache(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "cached.yml").write_text(_make_service_yaml("cached"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            result = catalog.load_services()
        assert len(result) == 1

    def test_get_service_by_slug(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "mysvc.yml").write_text(_make_service_yaml("mysvc"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            catalog.load_services()
            svc = catalog.get_service("mysvc")
        assert svc is not None
        assert svc["slug"] == "mysvc"

    def test_get_service_missing_returns_none(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "x.yml").write_text(_make_service_yaml("x"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            catalog.load_services()
            assert catalog.get_service("nonexistent") is None

    def test_get_services_returns_copies(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "svc.yml").write_text(_make_service_yaml("svc"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            catalog.load_services()
            services1 = catalog.get_services()
            services1[0]["name"] = "MODIFIED"
            services2 = catalog.get_services()
            assert services2[0]["name"] != "MODIFIED"

    def test_get_services_by_category(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "a.yml").write_text(_make_service_yaml("a", category="bandwidth"))
        (svc_dir / "b.yml").write_text(_make_service_yaml("b", category="depin"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            catalog.load_services()
            grouped = catalog.get_services_by_category()
        assert "bandwidth" in grouped
        assert "depin" in grouped


class TestValidate:
    def test_validate_valid(self, tmp_path):
        data = {
            "name": "Test",
            "slug": "test",
            "category": "bandwidth",
            "status": "active",
            "description": "desc",
            "docker": {"image": "test:latest"},
        }
        errors = catalog._validate(data, tmp_path / "test.yml")
        assert errors == []

    def test_validate_missing_fields(self, tmp_path):
        data = {"name": "Test"}
        errors = catalog._validate(data, tmp_path / "test.yml")
        assert len(errors) == 1
        assert "missing" in errors[0]

    def _base(self):
        return {
            "name": "Test",
            "slug": "test",
            "category": "bandwidth",
            "status": "active",
            "description": "desc",
            "docker": {"image": "test:latest", "env": [{"key": "K"}]},
        }

    def test_validate_rejects_bad_category_and_status(self, tmp_path):
        assert catalog._validate({**self._base(), "category": "bogus"}, tmp_path / "t.yml")
        assert catalog._validate({**self._base(), "status": "nope"}, tmp_path / "t.yml")

    def test_validate_rejects_malformed_docker_and_requirements(self, tmp_path):
        p = tmp_path / "t.yml"
        assert catalog._validate({**self._base(), "docker": {"image": 123}}, p)  # non-string image
        assert catalog._validate({**self._base(), "docker": {"image": "i", "env": [{"label": "no key"}]}}, p)
        assert catalog._validate({**self._base(), "docker": {"image": "i", "env": "notalist"}}, p)
        assert catalog._validate({**self._base(), "requirements": {"gpu": "yes"}}, p)  # non-bool

    def test_validate_rejects_malformed_collector_credentials(self, tmp_path):
        p = tmp_path / "t.yml"
        assert catalog._validate({**self._base(), "collector": "bad"}, p)
        assert catalog._validate({**self._base(), "collector": {"credentials": "bad"}}, p)
        assert catalog._validate({**self._base(), "collector": {"credentials": [{"kind": "api_key"}]}}, p)
        assert catalog._validate(
            {**self._base(), "collector": {"credentials": [{"key": "token", "kind": "magic"}]}},
            p,
        )
        assert catalog._validate(
            {**self._base(), "collector": {"credentials": [{"key": "token", "secret": "yes"}]}},
            p,
        )

    def test_validate_accepts_collector_credentials(self, tmp_path):
        assert catalog._validate(
            {
                **self._base(),
                "collector": {
                    "credentials": [
                        {
                            "key": "api_key",
                            "label": "API key",
                            "kind": "api_key",
                            "secret": True,
                            "required": True,
                            "source": "dashboard",
                            "expires_hours": 24,
                            "durable": True,
                        }
                    ]
                },
            },
            tmp_path / "t.yml",
        ) == []

    def test_validate_accepts_deploy_and_dashboard_credentials(self, tmp_path):
        payload = {
            **self._base(),
            "deploy": {
                "credentials": [
                    {
                        "key": "seed_bundle",
                        "label": "Seed bundle",
                        "kind": "file",
                        "secret": True,
                        "required": True,
                        "source": "CashPilot secret inventory",
                    }
                ]
            },
            "dashboard": {
                "credentials": [
                    {
                        "key": "token_cookie",
                        "label": "Dashboard token",
                        "kind": "cookie",
                        "secret": True,
                        "required": True,
                        "expires_hours": 12,
                    }
                ]
            },
        }
        assert catalog._validate(payload, tmp_path / "t.yml") == []

    def test_validate_rejects_malformed_deploy_and_dashboard_credentials(self, tmp_path):
        p = tmp_path / "t.yml"
        assert catalog._validate({**self._base(), "deploy": {"credentials": "bad"}}, p)
        assert catalog._validate({**self._base(), "dashboard": {"credentials": [{"key": "x", "kind": "bad"}]}}, p)

    def test_validate_allows_empty_image_for_non_deployable(self, tmp_path):
        # Extension/app-only services list an empty image and must still load.
        assert catalog._validate({**self._base(), "docker": {"image": ""}}, tmp_path / "t.yml") == []

    def test_all_shipped_services_pass_validation(self):
        # Guard: no real catalog entry is dropped by the loader's validation.
        assert len(catalog.load_services()) >= 21

class TestProviderAutomationContracts:
    def _svc(self, slug):
        return catalog.get_service(slug)

    def _credential_keys(self, service, section):
        return {item["key"] for item in (service.get(section, {}).get("credentials") or [])}

    def test_grass_runtime_uses_seed_bundle_asset(self):
        svc = self._svc("grass")
        assert svc["docker"]["image"] == "ghcr.io/assetforgeai-tech/internetincome-grass-desktop:7.5.1-minimal"
        assert "seed_bundle" in self._credential_keys(svc, "deploy")
        assert svc["deploy"]["automation"] == "seed_bundle"
        assert svc["deploy"]["runtime_assets"] == [
            {
                "provider": "grass",
                "asset_kind": "seed_bundle",
                "target": "/seed/grass-xdg-seed.tar.gz",
                "encoding": "base64",
            }
        ]

    def test_uprock_runtime_uses_seed_bundle_asset(self):
        svc = self._svc("uprock")
        assert svc["docker"]["image"] == "ghcr.io/assetforgeai-tech/internetincome-uprock:0.0.38-browser"
        assert "seed_bundle" in self._credential_keys(svc, "deploy")
        assert svc["deploy"]["automation"] == "seed_bundle"
        assert svc["deploy"]["runtime_assets"] == [
            {
                "provider": "uprock",
                "asset_kind": "seed_bundle",
                "target": "/seed/uprock-seed-bundle.tar.gz",
                "encoding": "base64",
            }
        ]

    def test_spide_runtime_uses_device_key_registration(self):
        svc = self._svc("spide")
        assert svc["deploy"]["automation"] == "device_key_register"
        assert "dashboard_token" in self._credential_keys(svc, "dashboard")

    def test_wipter_runtime_uses_env_login(self):
        svc = self._svc("wipter")
        keys = {item["key"] for item in svc["docker"]["env"]}
        assert {"WIPTER_EMAIL", "WIPTER_PASSWORD"} <= keys
        assert svc["deploy"]["automation"] == "env_login"
