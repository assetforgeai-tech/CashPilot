"""The shipped compose files must not use :latest (CashPilot-jz3).

The project's own rule is semver tags, never `latest`, and the security posture
claims images are pinned. The example compose files contradicted both: a user
following the quickstart got whatever was pushed most recently, with no way to
know what they were running and a breaking change possible on a routine
`docker compose pull`.

They now pin the major.minor tag, which is a real published tag: patch fixes
still arrive automatically, but a new minor or major needs a deliberate edit.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SHIPPED_COMPOSE = ["docker-compose.yml", "docker-compose.fleet.yml"]
CANONICAL_UI = "ghcr.io/assetforgeai-tech/cashpilot"
CANONICAL_WORKER = "ghcr.io/assetforgeai-tech/cashpilot-worker"
CANONICAL_IMAGES = (CANONICAL_UI, CANONICAL_WORKER)

_IMAGE = re.compile(r"^\s*image:\s*(\S+)", re.M)


def _images(name: str) -> list[str]:
    return _IMAGE.findall((PROJECT_ROOT / name).read_text())


def _cashpilot_images(name: str) -> list[str]:
    return [image for image in _images(name) if "cashpilot" in image]


@pytest.mark.parametrize("compose", SHIPPED_COMPOSE)
def test_shipped_compose_uses_the_fork_ghcr_images(compose):
    """The fork must not silently deploy the upstream Docker Hub images."""
    images = _cashpilot_images(compose)
    assert images, f"{compose} contains no CashPilot image"
    repositories = {image.rsplit(":", 1)[0] for image in images}
    assert repositories == set(CANONICAL_IMAGES), f"{compose} uses non-canonical images: {images}"


def test_release_workflows_do_not_import_upstream_release_tags():
    """Fork release drift must be calculated from fork tags only."""
    workflows = [
        PROJECT_ROOT / ".github" / "workflows" / "release.yml",
        PROJECT_ROOT / ".github" / "workflows" / "test.yml",
    ]
    offenders = [str(path) for path in workflows if "GeiserX/CashPilot.git" in path.read_text(encoding="utf-8")]
    assert not offenders, f"workflows import upstream release tags: {offenders}"


def test_workflows_fetch_fork_tags_into_an_isolated_namespace():
    """Fork tags must not collide with same-named tags already present locally."""
    test_workflow = (PROJECT_ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    release_workflow = (PROJECT_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    refspec = "git fetch --force origin 'refs/tags/*:refs/fork-tags/*'"
    assert refspec in test_workflow
    # release.yml has two independent checkouts: CI and version calculation.
    assert release_workflow.count(refspec) >= 2
    assert 'git diff --name-only "$LAST_TAG_REF"..HEAD' in release_workflow
    assert 'RANGE="refs/fork-tags/${LATEST}..HEAD"' in release_workflow
    # ghcr.io itself contains a colon, so splitting on the second field would
    # extract "io/..." instead of the image tag during the compose bump.
    assert "awk -F: '{print $NF}'" in release_workflow
    assert "cut -d: -f2" not in release_workflow


def test_build_and_release_workflows_use_the_fork_ghcr_images():
    """A release must publish and pin the same fork images users pull."""
    build = (PROJECT_ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
    release = (PROJECT_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "drumsergio/cashpilot" not in build
    assert "ghcr.io/${OWNER}/cashpilot" in build
    assert "ghcr.io/${OWNER}/cashpilot" in release


def test_fork_has_no_dockerhub_publication_workflow():
    """The fork must not keep a workflow that writes descriptions upstream."""
    assert not (PROJECT_ROOT / ".github" / "workflows" / "dockerhub-description.yml").exists()


@pytest.mark.parametrize("compose", SHIPPED_COMPOSE)
def test_no_latest_tag_in_shipped_compose(compose):
    offenders = [i for i in _images(compose) if i.endswith(":latest")]
    assert not offenders, (
        f"{compose} uses :latest for {offenders}. A user following the quickstart "
        "would not know what they are running, and a routine `docker compose pull` "
        "could carry a breaking change. Pin the major.minor tag instead."
    )


@pytest.mark.parametrize("compose", SHIPPED_COMPOSE)
def test_every_cashpilot_image_carries_an_explicit_tag(compose):
    """An untagged image is :latest by another name."""
    for image in _cashpilot_images(compose):
        assert ":" in image.split("/")[-1], f"{compose}: {image} has no explicit tag"


@pytest.mark.parametrize("compose", SHIPPED_COMPOSE)
def test_the_two_cashpilot_images_are_pinned_together(compose):
    """A UI and worker on different versions is a support problem nobody wants."""
    tags = {image.rsplit(":", 1)[1] for image in _cashpilot_images(compose)}
    assert len(tags) == 1, f"{compose}: UI and worker pinned to different tags {sorted(tags)}"


class TestTheComposePinTracksReleases:
    """CashPilot-yr7, and the direct cause of issue #188.

    docker-compose.yml pinned 1.4 while its own header claimed the images
    "track the `latest` tag" — and the string `:latest` it told you to replace
    appeared nowhere in the file. Following the quickstart therefore installed a
    version many releases behind.

    That is not cosmetic. radnet001 reported "Registration failed. Please try
    again." on v1.4, which is the first-run setup-token bug: v1.4.4 has the
    token gate in deps.py and no token field in onboarding.html, so the owner
    account could not be created at all. It had been fixed for months. The
    stale pin is what handed them the broken version.

    These tests are deliberately about DRIFT, not a fixed number: the pin must
    track the newest released major.minor, so this fails the next time the
    compose file falls behind.
    """

    def _newest_series(self) -> str:
        import re
        import subprocess

        out = subprocess.run(
            [
                "git",
                "for-each-ref",
                "--sort=-v:refname",
                "--format=%(refname:strip=2)",
                "refs/fork-tags/v*.*.*",
            ],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        ).stdout
        for line in out.splitlines():
            m = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", line.strip())
            if m:
                return f"{m.group(1)}.{m.group(2)}"
        if os.environ.get("CI"):
            pytest.fail(
                "no fork semver tags in refs/fork-tags — CI must fetch the fork tag refspec, "
                "otherwise this drift test silently passes and the pin can rot again"
            )
        pytest.skip("no fork semver tags available in refs/fork-tags")

    @pytest.mark.parametrize("name", ["docker-compose.yml", "docker-compose.fleet.yml"])
    def test_the_pin_matches_the_newest_released_series(self, name):
        import re

        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        # Comments included on purpose. docker-compose.fleet.yml's commented
        # remote-worker block is a template users uncomment and run, so a stale
        # pin there ships an old image just as surely as a live one.
        pins = set(
            re.findall(
                r"image: ghcr\.io/assetforgeai-tech/cashpilot(?:-worker)?:(\S+)",
                text,
            )
        )
        assert pins, f"{name} pins no cashpilot image"
        newest = self._newest_series()
        assert pins == {newest}, (
            f"{name} pins {sorted(pins)} but the newest released series is {newest}. "
            "A stale pin here is what gave issue #188 a version with a first-run bug "
            "that had been fixed for months."
        )

    def test_the_header_does_not_claim_to_track_latest(self):
        """The sentence that made the stale pin invisible.

        It told the reader to replace `:latest` — a string the file did not
        contain — so anyone checking whether they were current concluded they
        were.
        """
        text = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        header = text[: text.index("services:")]
        assert "track the `latest` tag" not in header
        assert "replace `:latest`" not in header

    def test_the_header_says_what_the_file_actually_does(self):
        text = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        header = text[: text.index("services:")]
        assert "PINNED" in header or "pinned" in header


class TestEveryWorkflowThatRunsTheSuiteFetchesTags:
    """The drift test above fails loudly when it finds no tags. That is right —
    a silent skip is how the pin rotted to 1.4 in the first place — but it means
    any workflow running pytest without tags cannot pass.

    test.yml was given `fetch-tags: true` when the drift test was written.
    release.yml was not, so its "Verify CI passes" job failed and blocked the
    release of six merged fixes. The test was working exactly as designed; the
    workflow was the thing that was wrong. This makes the requirement explicit
    so a third workflow cannot repeat it.
    """

    @staticmethod
    def _runs_the_drift_test(command: str) -> bool:
        """Whether a pytest invocation would actually collect the drift test.

        A marker or keyword filter means it would not. collector-live-check.yml
        runs `pytest tests/ -m live`, and no test here carries that marker — so
        requiring tags there would be a rule about a problem that workflow
        cannot have. The first version of this guard flagged it, which is how
        the distinction got noticed.
        """
        if "pytest" not in command:
            return False
        return " -m " not in command and " -k " not in command

    def _workflows_running_pytest(self):
        import yaml

        out = []
        for path in sorted((PROJECT_ROOT / ".github" / "workflows").glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            if "pytest" not in text:
                continue
            out.append((path.name, yaml.safe_load(text)))
        return out

    def test_at_least_two_workflows_run_the_suite(self):
        """Guards against this passing because the glob found nothing."""
        names = [n for n, _ in self._workflows_running_pytest()]
        assert len(names) >= 2, f"only {names} appear to run pytest — the scan is not seeing the workflows"

    def test_a_marker_filtered_run_is_not_required_to_fetch_tags(self):
        """The control that keeps this rule honest rather than merely strict."""
        assert not self._runs_the_drift_test("python -m pytest tests/ -m live -q")
        assert self._runs_the_drift_test("uv run pytest")
        assert self._runs_the_drift_test("pytest tests/ -v --tb=short")

    def test_each_such_job_checks_out_with_tags(self):
        offenders = []
        for name, doc in self._workflows_running_pytest():
            for job_name, job in (doc.get("jobs") or {}).items():
                steps = job.get("steps") or []
                if not any(self._runs_the_drift_test(str(step.get("run", ""))) for step in steps):
                    continue
                checkouts = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout")]
                for step in checkouts:
                    if not (step.get("with") or {}).get("fetch-tags"):
                        offenders.append(f"{name}:{job_name}")
        assert not offenders, (
            f"these run pytest without fetching tags, so the compose-pin drift test fails: {offenders}. "
            "Add `fetch-depth: 0` and `fetch-tags: true` to the checkout."
        )
