# QUANTCONNECT.COM - Democratizing Finance, Empowering Individuals.
# Lean CLI v1.0. Copyright 2021 QuantConnect Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import webbrowser
from typing import Dict, List, Tuple, Optional
import click
from lean.click import LeanCommand, ensure_options
from lean.components.api.api_client import APIClient
from lean.components.util.logger import Logger
from lean.container import container
from lean.models.api import (QCEmailNotificationMethod, QCNode, QCNotificationMethod, QCSMSNotificationMethod,
                             QCWebhookNotificationMethod, QCProject)
from lean.models.logger import Option
from lean.models.brokerages.cloud.cloud_brokerage import CloudBrokerage
from lean.models.configuration import Configuration, InfoConfiguration, InternalInputUserInput, OrganzationIdConfiguration
from lean.models.click_options import options_from_json
from lean.models.brokerages.cloud import all_cloud_brokerages

def _log_notification_methods(methods: List[QCNotificationMethod]) -> None:
    """Logs a list of notification methods."""
    logger = container.logger()

    email_methods = [method for method in methods if isinstance(method, QCEmailNotificationMethod)]
    email_methods = "None" if len(email_methods) == 0 else ", ".join(method.address for method in email_methods)

    webhook_methods = [method for method in methods if isinstance(method, QCWebhookNotificationMethod)]
    webhook_methods = "None" if len(webhook_methods) == 0 else ", ".join(method.address for method in webhook_methods)

    sms_methods = [method for method in methods if isinstance(method, QCSMSNotificationMethod)]
    sms_methods = "None" if len(sms_methods) == 0 else ", ".join(method.phoneNumber for method in sms_methods)

    logger.info(f"Email notifications: {email_methods}")
    logger.info(f"Webhook notifications: {webhook_methods}")
    logger.info(f"SMS notifications: {sms_methods}")


def _prompt_notification_method() -> QCNotificationMethod:
    """Prompts the user to add a notification method.

    :return: the notification method configured by the user
    """
    logger = container.logger()
    selected_method = logger.prompt_list("Select a notification method", [Option(id="email", label="Email"),
                                                                          Option(id="webhook", label="Webhook"),
                                                                          Option(id="sms", label="SMS")])

    if selected_method == "email":
        address = click.prompt("Email address")
        subject = click.prompt("Subject")
        return QCEmailNotificationMethod(address=address, subject=subject)
    elif selected_method == "webhook":
        address = click.prompt("URL")
        headers = {}

        while True:
            headers_str = "None" if headers == {} else ", ".join(f"{key}={headers[key]}" for key in headers)
            logger.info(f"Headers: {headers_str}")

            if not click.confirm("Do you want to add a header?", default=False):
                break

            key = click.prompt("Header key")
            value = click.prompt("Header value")
            headers[key] = value

        return QCWebhookNotificationMethod(address=address, headers=headers)
    else:
        phone_number = click.prompt("Phone number")
        return QCSMSNotificationMethod(phoneNumber=phone_number)


def _configure_brokerage(logger: Logger) -> CloudBrokerage:
    """Interactively configures the brokerage to use.

    :param logger: the logger to use
    :return: the cloud brokerage the user configured
    """
    brokerage_options = [Option(id=b, label=b.get_name()) for b in all_cloud_brokerages]
    return logger.prompt_list("Select a brokerage", brokerage_options).build(None,logger)


def _configure_live_node(logger: Logger, api_client: APIClient, cloud_project: QCProject) -> QCNode:
    """Interactively configures the live node to use.

    :param logger: the logger to use
    :param api_client: the API client to make API requests with
    :param cloud_project: the cloud project the user wants to start live trading for
    :return: the live node the user wants to start live trading on
    """
    nodes = api_client.nodes.get_all(cloud_project.organizationId)

    live_nodes = [node for node in nodes.live if not node.busy]
    if len(live_nodes) == 0:
        raise RuntimeError(
            f"You don't have any live nodes available, you can manage your nodes on https://www.quantconnect.com/organization/{cloud_project.organizationId}/resources")

    node_options = [Option(id=node, label=f"{node.name} - {node.description}") for node in live_nodes]
    return logger.prompt_list("Select a node", node_options)


def _configure_notifications(logger: Logger) -> Tuple[bool, bool, List[QCNotificationMethod]]:
    """Interactively configures how and when notifications should be sent.

    :param logger: the logger to use
    :return: whether notifications must be enabled for order events and insights, and the notification methods
    """
    logger.info(
        "You can optionally request for your strategy to send notifications when it generates an order or emits an insight")
    logger.info("You can use any combination of email notifications, webhook notifications and SMS notifications")
    notify_order_events = click.confirm("Do you want to send notifications on order events?", default=False)
    notify_insights = click.confirm("Do you want to send notifications on insights?", default=False)
    notify_methods = []

    if notify_order_events or notify_insights:
        _log_notification_methods(notify_methods)
        notify_methods.append(_prompt_notification_method())

        while True:
            _log_notification_methods(notify_methods)
            if not click.confirm("Do you want to add another notification method?", default=False):
                break
            notify_methods.append(_prompt_notification_method())

    return notify_order_events, notify_insights, notify_methods


def _configure_auto_restart(logger: Logger) -> bool:
    """Interactively configures whether automatic algorithm restarting must be enabled.

    :param logger: the logger to use
    :return: whether automatic algorithm restarting must be enabled
    """
    logger.info("Automatic restarting uses best efforts to restart the algorithm if it fails due to a runtime error")
    logger.info("This can help improve its resilience to temporary errors such as a brokerage API disconnection")
    return click.confirm("Do you want to enable automatic algorithm restarting?", default=True)

#TODO: same duplication present in commands\live.py
def _get_configs_for_options() -> Dict[Configuration, str]: 
    run_options: Dict[str, Configuration] = {}
    for module in all_cloud_brokerages:
        for config in module.get_all_input_configs([InternalInputUserInput, InfoConfiguration]):
            if config._id in run_options:
                raise ValueError(f'Options names should be unique. Duplicate key present: {config._id}')
            run_options[config._id] = config
    return list(run_options.values())

@click.command(cls=LeanCommand)
@click.argument("project", type=str)
@click.option("--brokerage",
              type=click.Choice([b.get_name() for b in all_cloud_brokerages], case_sensitive=False),
              help="The brokerage to use")
@options_from_json(_get_configs_for_options())
@click.option("--node", type=str, help="The name or id of the live node to run on")
@click.option("--auto-restart", type=bool, help="Whether automatic algorithm restarting must be enabled")
@click.option("--notify-order-events", type=bool, help="Whether notifications must be sent for order events")
@click.option("--notify-insights", type=bool, help="Whether notifications must be sent for emitted insights")
@click.option("--notify-emails",
              type=str,
              help="A comma-separated list of 'email:subject' pairs configuring email-notifications")
@click.option("--notify-webhooks",
              type=str,
              help="A comma-separated list of 'url:HEADER_1=VALUE_1:HEADER_2=VALUE_2:etc' pairs configuring webhook-notifications")
@click.option("--notify-sms", type=str, help="A comma-separated list of phone numbers configuring SMS-notifications")
@click.option("--push",
              is_flag=True,
              default=False,
              help="Push local modifications to the cloud before starting live trading")
@click.option("--open", "open_browser",
              is_flag=True,
              default=False,
              help="Automatically open the live results in the browser once the deployment starts")
def live(project: str,
         brokerage: str,
         node: str,
         auto_restart: bool,
         notify_order_events: Optional[bool],
         notify_insights: Optional[bool],
         notify_emails: Optional[str],
         notify_webhooks: Optional[str],
         notify_sms: Optional[str],
         push: bool,
         open_browser: bool,
         **kwargs) -> None:
    """Start live trading for a project in the cloud.

    PROJECT must be the name or the id of the project to start live trading for.

    By default an interactive wizard is shown letting you configure the deployment.
    If --brokerage is given the command runs in non-interactive mode.
    In this mode the CLI does not prompt for input or confirmation.
    In non-interactive mode the options specific to the given brokerage are required,
    as well as --node, --auto-restart, --notify-order-events and --notify-insights.
    """
    logger = container.logger()
    api_client = container.api_client()

    cloud_project_manager = container.cloud_project_manager()
    cloud_project = cloud_project_manager.get_cloud_project(project, push)

    cloud_runner = container.cloud_runner()
    finished_compile = cloud_runner.compile_project(cloud_project)

    if brokerage is not None:
        ensure_options(["brokerage", "node", "auto_restart", "notify_order_events", "notify_insights"])

        brokerage_instance = None
        [brokerage_instance] = [cloud_brokerage for cloud_brokerage in all_cloud_brokerages if cloud_brokerage.get_name() == brokerage]
        # update essential properties from brokerage to datafeed
        # needs to be updated before fetching required properties
        essential_properties = [brokerage_instance._convert_lean_key_to_variable(prop) for prop in brokerage_instance.get_essential_properties()]
        ensure_options(essential_properties)
        essential_properties_value = {brokerage_instance._convert_variable_to_lean_key(prop) : kwargs[prop] for prop in essential_properties}
        brokerage_instance.update_configs(essential_properties_value)
        # now required properties can be fetched as per data provider from esssential properties
        required_properties = [brokerage_instance._convert_lean_key_to_variable(prop) for prop in brokerage_instance.get_required_properties([OrganzationIdConfiguration, InternalInputUserInput])]
        ensure_options(required_properties)
        required_properties_value = {brokerage_instance._convert_variable_to_lean_key(prop) : kwargs[prop] for prop in required_properties}
        brokerage_instance.update_configs(required_properties_value)

        all_nodes = api_client.nodes.get_all(cloud_project.organizationId)
        live_node = next((n for n in all_nodes.live if n.id == node or n.name == node), None)

        if live_node is None:
            raise RuntimeError(f"You have no live node with name or id '{node}'")

        if live_node.busy:
            raise RuntimeError(f"The live node named '{live_node.name}' is already in use by '{live_node.usedBy}'")

        notify_methods = []

        if notify_emails is not None:
            for config in notify_emails.split(","):
                address, subject = config.split(":")
                notify_methods.append(QCEmailNotificationMethod(address=address, subject=subject))

        if notify_webhooks is not None:
            for config in notify_webhooks.split(","):
                address, *headers = config.split(":")
                headers = {header.split("=")[0]: header.split("=")[1] for header in headers}
                notify_methods.append(QCWebhookNotificationMethod(address=address, headers=headers))

        if notify_sms is not None:
            for phoneNumber in notify_sms.split(","):
                notify_methods.append(QCSMSNotificationMethod(phoneNumber=phoneNumber))
    else:
        brokerage_instance = _configure_brokerage(logger)
        live_node = _configure_live_node(logger, api_client, cloud_project)
        notify_order_events, notify_insights, notify_methods = _configure_notifications(logger)
        auto_restart = _configure_auto_restart(logger)

    brokerage_settings = brokerage_instance.get_settings()
    price_data_handler = brokerage_instance.get_price_data_handler()

    logger.info(f"Brokerage: {brokerage_instance.get_name()}")
    logger.info(f"Project id: {cloud_project.projectId}")
    logger.info(f"Environment: {brokerage_settings['environment'].title()}")
    logger.info(f"Server name: {live_node.name}")
    logger.info(f"Server type: {live_node.sku}")
    logger.info(f"Data provider: {price_data_handler.replace('Handler', '')}")
    logger.info(f"LEAN version: {cloud_project.leanVersionId}")
    logger.info(f"Order event notifications: {'Yes' if notify_order_events else 'No'}")
    logger.info(f"Insight notifications: {'Yes' if notify_insights else 'No'}")
    if notify_order_events or notify_insights:
        _log_notification_methods(notify_methods)
    logger.info(f"Automatic algorithm restarting: {'Yes' if auto_restart else 'No'}")

    if brokerage is None:
        click.confirm(f"Are you sure you want to start live trading for project '{cloud_project.name}'?",
                      default=False,
                      abort=True)

    live_algorithm = api_client.live.start(cloud_project.projectId,
                                           finished_compile.compileId,
                                           live_node.id,
                                           brokerage_settings,
                                           price_data_handler,
                                           auto_restart,
                                           cloud_project.leanVersionId,
                                           notify_order_events,
                                           notify_insights,
                                           notify_methods)

    logger.info(f"Live url: {live_algorithm.get_url()}")

    if open_browser:
        webbrowser.open(live_algorithm.get_url())
