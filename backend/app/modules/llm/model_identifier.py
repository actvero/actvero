"""Callable model identifiers shared by catalog and gateway publication.

New API aliases can contain interior ASCII spaces. Keep those exact names;
never silently trim or slugify a name that identifies a route or a price.
"""

from typing import Annotated

from pydantic import StringConstraints

ModelIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=False,
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9._:/@+ \-]*[A-Za-z0-9._:/@+\-])?$",
    ),
]
