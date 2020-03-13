import json
import re
import time
import logging

import boto3
from botocore.exceptions import ClientError

from functools import wraps
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    NamedTuple,
    Optional,
    Tuple,
    Union,
)

from boto3_type_annotations.ec2 import (
    Client,
    Instance,
    ServiceResource,
    Volume,
)

logger = logging.getLogger(__name__)


# Backoff implementation was shamelessly copied over from Ansible
# source code and adjusted for specific usecase.
def _exponential_backoff(
        retries: int = 10,
        delay: float = 2,
        backoff: float = 2,
        max_delay: float = 60) -> Callable:
    """
    Customizable exponential backoff strategy.
    Args:
        retries (int): Maximum number of times to retry a request.
        delay (float): Initial (base) delay.
        backoff (float): base of the exponent to use for exponential
            backoff.
        max_delay (int): Optional. If provided each delay generated is capped
            at this amount. Defaults to 60 seconds.
    Returns:
        Callable that returns a generator. This generator yields durations in
        seconds to be used as delays for an exponential backoff strategy.
    Usage:
        >>> backoff = _exponential_backoff()
        >>> backoff
        <function backoff_backoff at 0x7f0d939facf8>
        >>> list(backoff())
        [2, 4, 8, 16, 32, 60, 60, 60, 60, 60]
    """
    def backoff_gen() -> Iterator[float]:
        for retry in range(0, retries):
            sleep = delay * backoff ** retry
            yield (
                sleep
                if max_delay is None
                else min(sleep, max_delay)
            )

    return backoff_gen


class AWSRetry:
    """
    Implements a backoff algorithm/retry effect based on Status
    Code from Exceptions.
    """
    base_class = ClientError

    @staticmethod
    def status_code_from_exception(error: ClientError) -> str:
        return error.response['Error']['Code']

    @classmethod
    def _backoff(
            cls,
            backoff_strategy: Callable,
            catch_extra_error_codes: Optional[List[str]] = None) -> Callable:
        """
        Retry calling the Cloud decorated function using the provided
        backoff strategy.
        Args:
            backoff_strategy (callable): Callable that returns a generator. The
            generator should yield sleep times for each retry of the decorated
            function.
        """
        def deco(f: Callable) -> Callable:
            @wraps(f)
            def retry_func(*args, **kwargs):
                for delay in backoff_strategy():
                    try:
                        return f(*args, **kwargs)
                    except Exception as e:
                        if isinstance(e, cls.base_class):
                            response_code = cls.status_code_from_exception(e)
                            if cls.found(response_code, catch_extra_error_codes):
                                logger.info(f"{e}: Retrying in {delay} seconds...")
                                time.sleep(delay)
                            else:
                                raise e
                        else:
                            raise e

                return f(*args, **kwargs)

            return retry_func  # true decorator

        return deco

    @classmethod
    def exponential_backoff(
            cls,
            retries: int = 5,
            delay: float = 0.4,
            backoff: float = 2,
            max_delay: float = 5,
            catch_extra_error_codes: Optional[List[str]] = None) -> Callable:
        """
        Retry calling the Cloud decorated function using an exponential backoff.
        Kwargs:
            retries (int): Number of times to retry a failed request before giving up
                default=10
            delay (int or float): Initial delay between retries in seconds
                default=3
            backoff (int or float): backoff multiplier e.g. value of 2 will
                double the delay each retry
                default=1.1
            max_delay (int or None): maximum amount of time to wait between retries.
                default=60
        """
        return cls._backoff(
                _exponential_backoff(
                    retries=retries,
                    delay=delay,
                    backoff=backoff,
                    max_delay=max_delay),
                catch_extra_error_codes)

    @staticmethod
    def found(
            response_code: str,
            catch_extra_error_codes: Optional[List[str]] = None) -> bool:
        # This list of failures is based on this API Reference
        # http://docs.aws.amazon.com/AWSEC2/latest/APIReference/errors-overview.html
        #
        # TooManyRequestsException comes from inside botocore when it
        # does retrys, unfortunately however it does not try long
        # enough to allow some services such as API Gateway to
        # complete configuration.  At the moment of writing there is a
        # botocore/boto3 bug open to fix this.
        #
        # https://github.com/boto/boto3/issues/876 (and linked PRs etc)
        retry_on = [
            'RequestLimitExceeded',
            'Unavailable',
            'ServiceUnavailable',
            'InternalFailure',
            'InternalError',
            'TooManyRequestsException',
            'Throttling',
            'ThrottlingException',
        ]

        if catch_extra_error_codes:
            retry_on.extend(catch_extra_error_codes)

        not_found = re.compile(r'^\w+.NotFound')
        return (  # type: ignore
            response_code in retry_on
            or not_found.search(response_code)
        )


class ASG:
    """
    ASG and related EC2 instance discovery and management.
    """
    def __init__(self, sns_event: Dict) -> None:
        self.supported_events = (
            'autoscaling:EC2_INSTANCE_LAUNCH',
            'autoscaling:EC2_INSTANCE_TERMINATE',
            'autoscaling:TEST_NOTIFICATION',
        )

        try:
            msg = json.loads(sns_event['Records'][0]['Sns']['Message'])
            self.name = msg['AutoScalingGroupName']
            self.event = msg['Event']
            self.event_ec2_id = (
                msg['EC2InstanceId']
                if self.event != 'autoscaling:TEST_NOTIFICATION'
                else None
            )
        except Exception as e:
            raise Exception(f"Error parsing ASG SNS event message") from e

        if self.event not in self.supported_events:
            raise Exception(f"Unsupported event: {self.event}")

        self.is_launched: bool = (
            self.event != 'autoscaling:EC2_INSTANCE_TERMINATE')

        self.reset_cache()

    def reset_cache(self) -> None:
        self._asg_boto3_client: Client = None
        self._asg_tags: Dict[str, str] = {}
        self._asg_ec2_ids: List[str] = []

        self._ec2_boto3_client: Client = None
        self._ec2_instances: List[Instance] = []

    @staticmethod
    def _resource_tags_to_dict(
            tags: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
        resource_tags: Dict[str, Dict[str, str]] = {}
        for tag in tags:
            if tag['ResourceId'] not in resource_tags:
                resource_tags[tag['ResourceId']] = {}

            resource_tags[tag['ResourceId']][tag['Key']] = tag.get('Value', '')

        return resource_tags

    @staticmethod
    def _tags_to_dict(
            tags: List[Dict[str, str]]) -> Dict[str, str]:
        return {
            tag['Key']: tag.get('Value', '')
            for tag
            in tags
        }

    @property
    def _asg_cl(self) -> Client:
        if not self._asg_boto3_client:
            self._asg_boto3_client = boto3.client('autoscaling')

        return self._asg_boto3_client

    @property
    def _ec2_cl(self) -> Client:
        if not self._ec2_boto3_client:
            self._ec2_boto3_client = boto3.client('ec2')

        return self._ec2_boto3_client

    @property  # noqa
    @AWSRetry.exponential_backoff()
    def tags(self) -> Dict[str, str]:
        if not self._asg_tags:
            response = self._asg_cl.describe_tags(
                Filters=[
                    {
                        'Name': 'auto-scaling-group',
                        'Values': [self.name]
                    }
                ]
            )
            try:
                self._asg_tags = self. _resource_tags_to_dict(
                    response['Tags']
                )[self.name]
            except KeyError:
                raise ValueError(
                    f"There is no autoscaling group named: {self.name}")

        return self._asg_tags

    @property  # noqa
    @AWSRetry.exponential_backoff()
    def instance_ids(self) -> List[str]:
        if not self._asg_ec2_ids:
            response = self._asg_cl.describe_auto_scaling_groups(
                AutoScalingGroupNames=[self.name]
            )
            self._asg_ec2_ids = [
                instance['InstanceId']
                for instance
                in response['AutoScalingGroups'][0]['Instances']
                if instance['LifecycleState'] in [
                        'InService',
                        'Pending',
                        'Pending:Proceed',
                        'Pending:Wait',
                    ]
            ]

            logger.debug(
                f"ASG {self.name} > EC2 Ids discovered: {self._asg_ec2_ids}")

        return self._asg_ec2_ids

    @property  # noqa
    @AWSRetry.exponential_backoff()
    def _instances(self) -> List[Instance]:
        if not self._ec2_instances:
            self._ec2_instances = [
                boto3.resource('ec2').Instance(ec2_id)
                for ec2_id
                in self.instance_ids
            ]

        return self._ec2_instances

    def get_instance_id_attr(
            self,
            attr: str,
            do_skip: bool = True,
            keep_states: Tuple[str, ...] = ('pending', 'running'),
            default: Any = None,
            mod: Callable = lambda x: x) -> Dict[str, Any]:
        return {
            instance.id: (
                mod(getattr(instance, attr))
                if instance.state['Name'] in keep_states
                else default
            )
            for instance
            in self._instances
            if not do_skip or instance.state['Name'] in keep_states
        }

    @property
    def instance_private_ips(self) -> Dict[str, str]:
        return self.get_instance_id_attr('private_ip_address')

    @property
    def instance_public_ips(self) -> Dict[str, str]:
        return self.get_instance_id_attr('public_ip_address')

    @property
    def instance_tags(self) -> Dict[str, Dict[str, str]]:
        return self.get_instance_id_attr(
            attr='tags',
            do_skip=False,
            default={},
            mod=self._tags_to_dict
        )

    @AWSRetry.exponential_backoff()
    def apply_instance_tags(
            self,
            tags_state: Dict[str, List[Dict[str, str]]]) -> None:
        for ec2_id, ec2_tags in tags_state.items():
            self._ec2_cl.create_tags(Resources=[ec2_id], Tags=ec2_tags)


class R53:
    """
    Route53 record state management for ASG.
    """
    def __init__(self,
            asg: ASG,
            tag_uniq: str = 'tool:asg:dns:internal:uniq',
            tag_shared: str = 'tool:asg:dns:internal:shared',
            tag_set_suffix: str = ':set',
            is_internal_ip: bool = True,
            is_private_dns: Optional[bool] = None) -> None:
        self._asg = asg

        self.r53_tag_set_suffix = tag_set_suffix
        self.r53_uniq_tag = tag_uniq
        self.r53_uniq_tag_marker = f"{self.r53_uniq_tag}{self.r53_tag_set_suffix}"
        self.r53_shared_tag = tag_shared
        self.r53_shared_tag_marker = f"{self.r53_shared_tag}{self.r53_tag_set_suffix}"

        self.is_internal_ip = is_internal_ip
        self.is_private_dns = is_private_dns

        self._r53_ips: Dict[str, str] = (
            self._asg.instance_private_ips
            if self.is_internal_ip
            else self._asg.instance_public_ips
        )

        self._r53_boto3_client: Client = None
        self._uniq: Dict[str, Union[str, List[Dict]]] = {}
        self._shared: Dict[str, Union[str, List[Dict]]] = {}
        self._zone_ids: Dict[str, str] = {}

        self._ec2_tags_to_add: Dict[str, List[Dict[str, str]]] = {}

    @property
    def _r53_cl(self) -> Client:
        if not self._r53_boto3_client:
            self._r53_boto3_client = boto3.client('route53')

        return self._r53_boto3_client

    @AWSRetry.exponential_backoff()
    def _zone_id(self, domain: str) -> str:
        if domain not in self._zone_ids:
            response = self._r53_cl.list_hosted_zones_by_name(DNSName=domain)
            try:
                self._zone_ids[domain] = [
                    zone['Id']
                    for zone in response['HostedZones']
                    if (self.is_private_dns is None
                        or zone['Config']['PrivateZone'] == self.is_private_dns)
                ][0]
            except IndexError:
                raise Exception(
                    f"Error retrieving information about DNS zone: '{domain}'")

        return self._zone_ids[domain]

    def _ec2id_to_tag_map(
            self,
            tag: str,
            values: List[str] = None) -> Dict[str, Optional[str]]:
        return {
            ec2_id: (
                self._asg.instance_tags[ec2_id].get(tag)
                if (
                    not values
                    or self._asg.instance_tags[ec2_id].get(tag) in values
                )
                else None
            )
            for ec2_id
            in self._asg.instance_ids
        }

    def _ec2id_no_tag(self, tag: str, values: List[str] = None) -> List[str]:
        return [
            tag_key
            for tag_key, tag_value
            in self._ec2id_to_tag_map(tag, values).items()
            if not tag_value
        ]

    def _ec2id_by_tag(self, tag: str, value: str) -> List[str]:
        return [
            tag_key
            for tag_key, tag_value
            in self._ec2id_to_tag_map(tag).items()
            if tag_value == value
        ]

    def _ec2id_append_tag(self, ec2_id: str, key: str, value: str) -> None:
        if not ec2_id:
            return

        if ec2_id in self._ec2_tags_to_add:
            self._ec2_tags_to_add[ec2_id].append(
                {
                    'Key': key,
                    'Value': value
                }
            )
        else:
            self._ec2_tags_to_add[ec2_id] = [
                {
                    'Key': key,
                    'Value': value
                }
            ]

    @property
    def shared(self) -> Dict[str, Union[str, List[Dict]]]:
        if self._shared:
            return self._shared

        if not self._asg.tags.get(self.r53_shared_tag):
            self._shared = {}
            return self._shared

        (
            self._shared['host'],
            self._shared['domain']
        ) = self._asg.tags.get(self.r53_shared_tag).split(':')

        self._shared['zone_id'] = self._zone_id(self._shared['domain'])
        hostname = f"{self._shared['host']}.{self._shared['domain']}".strip('.')
        self._shared['records'] = [
            {
                'Name': hostname,
                'Type': 'A',
                'TTL': 10,
                'ResourceRecords': [
                    {'Value': ip}
                    for ip
                    in self._r53_ips.values()
                ]
            }
        ]

        for ec2_id in self._ec2id_no_tag(
                self.r53_shared_tag_marker,
                [hostname]):
            self._ec2id_append_tag(
                ec2_id,
                self.r53_shared_tag_marker,
                hostname
            )

        return self._shared

    @property
    def uniq(self) -> Dict[str, Union[str, List[Dict]]]:
        if self._uniq:
            return self._uniq

        if not self._asg.tags.get(self.r53_uniq_tag):
            self._uniq = {}
            return self._uniq

        (
            self._uniq['host'],
            self._uniq['domain']
        ) = self._asg.tags.get(self.r53_uniq_tag).split(':')

        self._uniq['zone_id'] = self._zone_id(self._uniq['domain'])
        self._uniq['records'] = []

        # NOTE: Parse individual host entries if '[' is in hostname.
        # e.g. host[1-3].domain.com wil be interpreted as 3 uniq hostnames:
        # host1.domain.com, host2.domain.com, host3.domain.com
        if '[' in self._uniq['host']:
            Hostname = NamedTuple(
                'Hostname',
                [
                    ('prefix', str),
                    ('min', int),
                    ('max', int),
                    ('suffix', str)
                ]
            )

            try:
                host = Hostname(  # type: ignore
                    *[
                        int(i)  # type: ignore
                        if i.isdigit()  # type: ignore
                        else i
                        for i
                        in re.match(  # type: ignore
                            r'(.*)\[([0-9]+)-([0-9])+\](.*)',
                            self._uniq['host']
                        ).groups()
                    ]
                )
            except Exception as e:
                raise ValueError(
                        f"Error parsing host numeration from '{self._uniq['host']}'"
                    ) from e

            hostnames = [
                f"{host.prefix}{i}{host.suffix}.{self._uniq['domain']}".strip('.')
                for i
                in range(host.min, host.max + 1)
            ]
            record_count = min(len(hostnames), len(self._asg.instance_ids))
        else:
            hostnames = [
                f"{self._uniq['host']}.{self._uniq['domain']}".strip('.')
            ]
            record_count = 1

        ec2_free_ids = self._ec2id_no_tag(self.r53_uniq_tag_marker, hostnames)

        for i in range(0, record_count):
            hostname = hostnames[i]

            ec2_id: Optional[str] = None

            if self._ec2id_by_tag(self.r53_uniq_tag_marker, hostname):
                ec2_id = self._ec2id_by_tag(self.r53_uniq_tag_marker, hostname)[-1]
                logger.debug(f"EC2 {ec2_id} > already tagged")

            elif ec2_free_ids:
                ec2_id = ec2_free_ids.pop()
                logger.debug(f"EC2 {ec2_id} > new Id assigned for tagging")
                self._ec2id_append_tag(ec2_id, self.r53_uniq_tag_marker, hostname)

            else:
                logger.error("No EC2 Ids available for tagging")

            if ec2_id and ec2_id not in self._r53_ips:
                logger.warning(
                    f"EC2 {ec2_id} > no IP was discovered for this Id. Retrying")
                self._asg.reset_cache()
                if ec2_id not in self._r53_ips:
                    logger.error(
                        f"EC2 {ec2_id} > Retry did not help. Skipping this Id")
                    ec2_id = None

            if ec2_id:
                self._uniq['records'].append(  # type: ignore
                    {
                        'Name': hostname,
                        'Type': 'A',
                        'TTL': 10,
                        'ResourceRecords': [
                            {
                                'Value': self._r53_ips[ec2_id]
                            }
                        ]
                    }
                )

        return self._uniq

    @AWSRetry.exponential_backoff()
    def apply_dns(self) -> None:
        r53_changes_shared = [
            {
                'Action': 'UPSERT',
                'ResourceRecordSet': record
            }
            for record
            in self.shared.get('records', [])
        ]

        r53_changes_uniq = [
            {
                'Action': 'UPSERT',
                'ResourceRecordSet': record
            }
            for record
            in self.uniq.get('records', [])
        ]

        # NOTE: Determine if we can perform Route53 API change request in one
        # go or have to split it for "shared" and "uniq" DNS changes, based on
        # Route53 zone ID.
        if ('zone_id' in self.shared
                and 'zone_id' in self.uniq
                and self.shared['zone_id'] == self.uniq['zone_id']
                and (r53_changes_shared or r53_changes_uniq)):
            self._r53_cl.change_resource_record_sets(
                HostedZoneId=self.shared['zone_id'],
                ChangeBatch={
                    'Changes': r53_changes_shared + r53_changes_uniq
                }
            )

        else:
            if 'zone_id' in self.shared and r53_changes_shared:
                self._r53_cl.change_resource_record_sets(
                    HostedZoneId=self.shared['zone_id'],
                    ChangeBatch={
                        'Changes': r53_changes_shared
                    }
                )

            if 'zone_id' in self.uniq and r53_changes_uniq:
                self._r53_cl.change_resource_record_sets(
                    HostedZoneId=self.uniq['zone_id'],
                    ChangeBatch={
                        'Changes': r53_changes_uniq
                    }
                )

    @property
    def ec2_tag_state(self) -> Dict[str, List[Dict[str, str]]]:
        return self._ec2_tags_to_add


class EC2:
    """
    EC2 management.
    """
    def __init__(self, instance_id: str) -> None:
        self._id = instance_id
        self._ec2_instance = None

    @property  # noqa
    @AWSRetry.exponential_backoff()
    def _instance(self) -> Instance:
        if not self._ec2_instance:
            self._ec2_instance = boto3.resource('ec2').Instance(self._id)

        return self._ec2_instance

    @property
    def volumes(self) -> Dict[str, str]:
        return {
            dev['Ebs']['VolumeId']: dev['DeviceName']
            for dev
            in self._instance.block_device_mappings
            if dev.get('Ebs', {}).get('Status') == 'attached'
        }

    @property
    def tags(self) -> Dict[str, str]:
        return {
            tag['Key']: tag['Value']
            for tag
            in self._instance.tags
        }


class EBS:
    """
    EBS Volume management.
    """
    def __init__(self, id: str) -> None:
        self._id = id
        self._ec2_volume = None

    @property  # noqa
    @AWSRetry.exponential_backoff()
    def _volume(self) -> Volume:
        if not self._ec2_volume:
            self._ec2_volume = boto3.resource('ec2').Volume(self._id)

        return self._ec2_volume

    @AWSRetry.exponential_backoff()
    def add_tags(self, tags: Dict[str, str]) -> None:
        self._volume.create_tags(
            Tags=[
                {
                    'Key': key,
                    'Value': value
                }
                for key, value
                in tags.items()
            ]
        )
