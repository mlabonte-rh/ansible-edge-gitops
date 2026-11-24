import base64
import os
import subprocess

# import logging
import pytest
from ocp_resources.secret import Secret
from ocp_resources.virtual_machine import VirtualMachine
from openshift.dynamic.exceptions import NotFoundError
from playwright.sync_api import sync_playwright
from validatedpatterns_tests.interop import application, components, subscription

from .helpers import (
    kubeadmin_password,
    route_url,
)


def _results_dir():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".results")
    os.makedirs(path, exist_ok=True)
    return path


def _openshift_login(page, url, password):
    page.goto(url)
    page.get_by_label("Username *").fill("kubeadmin")
    page.get_by_label("Password *").fill(password)
    page.get_by_role("button", name="Log in").click()


@pytest.mark.parametrize(
    "openshift_dyn_client",
    ["VP_HUBCONFIG"],
    indirect=True,
)
def test_subscription_status_hub(openshift_dyn_client):
    expected_subs = {
        "openshift-gitops-operator": ["openshift-gitops-operator"],
        "patterns-operator": ["patterns-operator"],
        "odf-operator": ["openshift-storage"],
        "kubevirt-hyperconverged": ["openshift-cnv"],
        "ansible-automation-platform-operator": ["ansible-automation-platform"],
    }

    subscription.assert_subscription_status(openshift_dyn_client, expected_subs)


@pytest.mark.parametrize(
    "openshift_dyn_client",
    ["VP_HUBCONFIG"],
    indirect=True,
)
def test_site_reachable_hub(openshift_dyn_client):

    components.assert_site_reachable(openshift_dyn_client)


@pytest.mark.parametrize(
    "openshift_dyn_client",
    ["VP_HUBCONFIG"],
    indirect=True,
)
def test_pod_status_hub(openshift_dyn_client):
    projects = [
        "patterns-operator",
        "ansible-automation-platform",
        "vp-gitops",
        "edge-gitops-vms",
        "vault",
    ]
    skip_check = []

    components.assert_pod_status(openshift_dyn_client, projects, skip_check)


@pytest.mark.parametrize(
    "openshift_dyn_client",
    ["VP_HUBCONFIG"],
    indirect=True,
)
def test_argocd_reachable_hub(openshift_dyn_client):
    components.assert_argocd_reachable(openshift_dyn_client)


@pytest.mark.parametrize(
    "openshift_dyn_client",
    ["VP_HUBCONFIG"],
    indirect=True,
)
def test_argocd_applications_health_hub(openshift_dyn_client):
    projects = ["vp-gitops"]

    application.assert_argocd_applications(openshift_dyn_client, projects)


@pytest.mark.parametrize(
    "openshift_dyn_client",
    ["VP_HUBCONFIG"],
    indirect=True,
)
def test_vm_status_hub(openshift_dyn_client):
    expected_vms = {
        "edge-gitops-vms": ["rhel10-kiosk-001", "rhel9-kiosk-001", "rhel8-kiosk-001"],
    }

    missing_vms = []
    unhealthy_vms = []

    for namespace, vm_list in expected_vms.items():
        for vm in vm_list:
            try:
                vms = VirtualMachine.get(
                    dyn_client=openshift_dyn_client, namespace=namespace, name=vm
                )
                vm = next(vms)
            except NotFoundError:
                missing_vms.append(f"{vm} in {namespace} namespace")
                continue

            if not vm.ready:
                unhealthy_vms.append(
                    f"{vm.instance.metadata.name} in {namespace} namespace is {vm.printable_status}"
                )

    errors = []

    if missing_vms:
        errors.append(f"Missing vms: {', '.join(missing_vms)}")

    if unhealthy_vms:
        errors.append(f"Unhealthy vms: {', '.join(unhealthy_vms)}")

    assert not errors, "VM status check failed:\n" + "\n".join(errors)


@pytest.mark.parametrize(
    "openshift_dyn_client",
    ["VP_HUBCONFIG"],
    indirect=True,
)
# @pytest.mark.skip(reason="Disabled pending fix")
def test_aap_login(openshift_dyn_client):
    console_url = route_url(openshift_dyn_client, "openshift-console", "console")
    aap_url = route_url(openshift_dyn_client, "ansible-automation-platform", "aap")
    password = kubeadmin_password()

    # os.environ["KUBECONFIG"] = os.getenv("VP_HUBCONFIG", "")

    # # Get the AAP password via the script.
    # for attempt in range(1, max_retries + 1):
    #     result = subprocess.run(
    #         ["bash", "../../pattern.sh", "../../scripts/ansible_get_credentials.sh"],
    #         capture_output=True,
    #         text=True,
    #         check=False,
    #     )
    #     if result.returncode == 0:
    #         break
    #     time.sleep(delay)

    aapsecret = next(
        Secret.get(
            dyn_client=openshift_dyn_client,
            namespace="ansible-automation-platform",
            name="aap-admin-password"
        ),
        None
    )

    if aapsecret:
        decoded_password = base64.b64decode(aapsecret.instance.data["password"]).decode("utf-8")
        # logger.info(decoded_password)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        context.set_default_timeout(120_000)
        page = context.new_page()
        try:
            # Log in to console
            page.goto(console_url)
            _openshift_login(page, console_url, password)

            page.wait_for_timeout(5000)

            # Dismiss welcome screen if visible
            welcome = page.get_by_role("button", name="Close")
            if welcome.is_visible(timeout=60):
                welcome.click()

            # Log in to AAP
            page.goto(aap_url)
            page.get_by_role("textbox", name="Username").fill("admin")
            page.get_by_role("textbox", name="Password").fill(decoded_password)
            page.get_by_role("button", name="Log in").click()

            # Make sure login succeeded
            page.get_by_role("button", name="Settings").click()

        finally:
            context.close()
            browser.close()

