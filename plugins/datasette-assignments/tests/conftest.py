import pytest
from datasette.app import Datasette


@pytest.fixture
def anyio_backend():
    return "asyncio"


# datasette_upload_csvs calls the old `permission_allowed` API which was
# removed in datasette>=1.0a35.  Shim it so the broken plugin doesn't
# crash menu rendering in tests.
if not hasattr(Datasette, "permission_allowed"):
    async def _permission_allowed_shim(self, actor, action, default=False):
        return default
    Datasette.permission_allowed = _permission_allowed_shim
