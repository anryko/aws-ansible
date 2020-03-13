import logging

from typing import (
    Dict,
    List,
    Optional,
    Tuple,
)

from aws import ASG, R53, EC2, EBS

logger = logging.getLogger(__name__)


def asg_tag_ec2_volumes(
        event: Dict,
        transfer_tag_keys: Optional[Tuple[str, ...]] = None) -> None:
    asg = ASG(event)

    logger.info(f"ASG {asg.name} > asg_tag_ec2_volumes triggered")

    if not asg.is_launched:
        logger.info('Skipping! Nothing to do on this event: {asg.event}')
        return

    if transfer_tag_keys is None:
        transfer_tag_keys = (
            'Automated',
            'Market',
            'Environment',
            'Service',
            'Group',
            'Version',
            'Timestamp',
            'BusinessUnit',
        )

    ec2_ids: List[str] = (
        [asg.event_ec2_id]
        if asg.event_ec2_id
        else asg.instance_ids
    )

    for ec2_id in ec2_ids:
        logger.debug(f"EC2 {ec2_id} > volume tagging initiated")

        ec2 = EC2(ec2_id)

        logger.debug(f"EC2 {ec2_id} > tags discovered: {ec2.tags}")

        transfer_tags: Dict[str, str] = {
            tag_key: ec2.tags[tag_key]
            for tag_key in transfer_tag_keys if tag_key in ec2.tags}

        logger.debug(f"EC2 {ec2_id} > prepared volume tags: {transfer_tags}")
        logger.debug(f"EC2 {ec2_id} > volumes: {ec2.volumes}")

        volumes_tags: Dict[str, Dict[str, str]] = {
            volume_id: {
                **{'Name': f"{ec2.tags.get('Name', asg.name)}-{volume_mount}"},
                **transfer_tags
            }
            for volume_id, volume_mount
            in ec2.volumes.items()
        }

        logger.info(f"EC2 {ec2_id} > adding volume tags: {volumes_tags}")

        for volume_id, volume_tags in volumes_tags.items():
            EBS(volume_id).add_tags(volume_tags)


def asg_add_dns_by_tag(
        event: Dict,
        tag_uniq: str,
        tag_shared: str,
        is_internal_ip: bool) -> None:
    asg = ASG(event)

    r53 = R53(
        asg,
        tag_uniq=tag_uniq,
        tag_shared=tag_shared,
        is_internal_ip=is_internal_ip
    )

    logger.info(f"ASG {asg.name} > asg_add_dns_by_tag triggered")
    logger.info(f"ASG {asg.name} > shared DNS config: {r53.shared}")
    logger.info(f"ASG {asg.name} > uniq DNS config: {r53.uniq}")

    r53.apply_dns()

    logger.info(f"ASG {asg.name} > applied DNS configs")

    logger.info(f"ASG {asg.name} > EC2 tags diff: {r53.ec2_tag_state}")

    asg.apply_instance_tags(r53.ec2_tag_state)

    logger.info(f"ASG {asg.name} > Applied EC2 tags diff")
