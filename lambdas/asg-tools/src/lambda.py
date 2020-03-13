import logging
import json

from typing import (
    Any,
    Dict,
)

import utils

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)


def handler(event: Dict, context: Any) -> None:
    logging.debug(f"Event: {json.dumps(event)}")

    utils.asg_tag_ec2_volumes(event)

    utils.asg_add_dns_by_tag(
        event,
        tag_uniq='tool:asg:dns:internal:uniq',
        tag_shared='tool:asg:dns:internal:shared',
        is_internal_ip=True
    )

    utils.asg_add_dns_by_tag(
        event,
        tag_uniq='tool:asg:dns:public:uniq',
        tag_shared='tool:asg:dns:public:shared',
        is_internal_ip=False
    )
