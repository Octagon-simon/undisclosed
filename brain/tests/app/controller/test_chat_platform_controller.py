# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========

import pytest
from pathlib import Path

from app.controller import chat_platform_controller
from app.controller.chat_platform_controller import (
    ProviderIn,
    ProviderPreferIn,
    ConfigIn,
    RemoteSubAgentProviderIn,
    get_providers,
    get_provider,
    create_provider,
    update_provider,
    delete_provider,
    set_provider_prefer,
    list_configs,
    get_config,
    create_config,
    update_config,
    delete_config,
    get_config_info,
    create_history,
    update_history,
    get_server_capabilities,
    get_user_key,
    get_share_info,
    create_share,
    list_remote_sub_agent_providers,
    create_remote_sub_agent_provider,
    update_remote_sub_agent_provider,
    delete_remote_sub_agent_provider,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_home(tmp_path, monkeypatch):
    """Fixture to isolate ~/.undisclosed during tests."""
    monkeypatch.setattr(chat_platform_controller, "_home", lambda: tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_providers_crud(mock_home):
    # 1. Initially empty
    providers = await get_providers()
    assert providers == []

    # 2. Create provider
    data = ProviderIn(
        provider_name="OPENAI",
        model_type="custom",
        api_key="sk-test",
        endpoint_url="https://api.openai.com/v1",
        encrypted_config={"temp": "value"},
        prefer=False,
    )
    p = await create_provider(data)
    assert p["id"] == 1
    assert p["provider_name"] == "OPENAI"
    assert p["prefer"] is False

    # 3. List contains it
    providers = await get_providers()
    assert len(providers) == 1
    assert providers[0]["id"] == 1

    # 4. Get by ID
    p_get = await get_provider(id=1)
    assert p_get["id"] == 1

    # 5. Set prefer
    await set_provider_prefer(ProviderPreferIn(provider_id=1))
    p_get_pref = await get_provider(id=1)
    assert p_get_pref["prefer"] is True

    # 6. Update
    data.api_key = "sk-updated"
    p_upd = await update_provider(id=1, data=data)
    assert p_upd["api_key"] == "sk-updated"

    # 7. Delete
    await delete_provider(id=1)
    providers = await get_providers()
    assert providers == []


@pytest.mark.asyncio
async def test_configs_crud(mock_home):
    # 1. Initially empty
    configs = await list_configs()
    assert configs == []

    # 2. Create config
    data = ConfigIn(
        config_name="GITHUB_TOKEN",
        config_value="ghp_test",
        config_group="Github",
    )
    c = await create_config(data)
    assert c["id"] == 1
    assert c["config_name"] == "GITHUB_TOKEN"

    # 3. List
    configs = await list_configs(config_group="Github")
    assert len(configs) == 1
    assert configs[0]["id"] == 1

    # 4. Get config
    c_get = await get_config(config_id=1)
    assert c_get["config_name"] == "GITHUB_TOKEN"

    # 5. Update config
    data.config_value = "ghp_updated"
    c_upd = await update_config(config_id=1, data=data)
    assert c_upd["config_value"] == "ghp_updated"

    # 6. Delete config
    await delete_config(config_id=1)
    configs = await list_configs()
    assert configs == []


@pytest.mark.asyncio
async def test_config_info():
    info = await get_config_info()
    assert "Slack" in info
    assert "Github" in info


@pytest.mark.asyncio
async def test_mock_endpoints(mock_home):
    key = await get_user_key()
    assert key["key"] == "local-key"

    share_info = await get_share_info("tok")
    assert share_info["share_token"] == "tok"

    share_post = await create_share()
    assert "share_token" in share_post

    # Test history create/update
    history_res = await create_history({
        "task_id": "test_id",
        "question": "test question",
        "project_name": "Test Project",
    })
    assert history_res["task_id"] == "test_id"
    assert history_res["project_name"] == "Test Project"

    history_upd = await update_history("test_id", {
        "project_name": "Updated Project",
    })
    assert history_upd["project_name"] == "Updated Project"

    # Test server capabilities
    caps = await get_server_capabilities()
    assert caps["features"]["connector_gateway"]["enabled"] is False


@pytest.mark.asyncio
async def test_remote_sub_agents_crud(mock_home):
    # 1. List
    agents = await list_remote_sub_agent_providers()
    assert agents == []

    # 2. Create
    data = RemoteSubAgentProviderIn(
        provider_name="gemini_agents",
        model_type="gemini",
        api_key="api_key",
        enabled=True,
    )
    a = await create_remote_sub_agent_provider(data)
    assert a["id"] == 1
    assert a["provider_name"] == "gemini_agents"

    # 3. List with filter
    agents = await list_remote_sub_agent_providers(provider_name="gemini_agents")
    assert len(agents) == 1

    # 4. Update
    data.api_key = "updated_key"
    a_upd = await update_remote_sub_agent_provider(provider_id=1, data=data)
    assert a_upd["api_key"] == "updated_key"

    # 5. Delete
    await delete_remote_sub_agent_provider(provider_id=1)
    agents = await list_remote_sub_agent_providers()
    assert agents == []
