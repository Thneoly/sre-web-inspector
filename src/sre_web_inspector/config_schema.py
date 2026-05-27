from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RetryConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    times: int = Field(default=1, ge=1)
    interval_ms: int = Field(default=1000, ge=0)


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    concurrency: int = Field(default=1, ge=1)
    output_dir: str = "outputs"
    run_id: str | None = None
    timeout: int = Field(default=60_000, ge=1)
    retry: RetryConfig = Field(default_factory=RetryConfig)


class BrowserConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    exe_dir: str | None = None
    browser_path: str | None = None
    user_data_dir: str | None = None
    headless: bool = False
    slow_mo: int = Field(default=300, ge=0)
    ignore_https_errors: bool = True
    no_viewport: bool = True
    start_maximized: bool = True
    extra_args: list[str] | None = None


class ReplayRequestConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    url: str
    params: dict[str, Any] | None = None
    headers: dict[str, str] | None = None
    body_type: Literal["json", "form"] = "json"
    data: Any | None = None
    form: dict[str, Any] | None = None
    timeout: int | None = Field(default=None, ge=1)
    retry: RetryConfig | None = None

    @field_validator("method", mode="before")
    @classmethod
    def upper_method(cls, value: Any) -> Any:
        return value.upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_post_body(self) -> "ReplayRequestConfig":
        if self.method == "POST" and self.body_type == "form" and self.form is None:
            self.form = {}
        if self.method == "POST" and self.body_type == "json" and self.data is None:
            self.data = {}
        return self


class WaitRequestConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str | None = None
    keyword: str
    timeout: int = Field(default=30_000, ge=1)


class WaitResponseConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str | None = None
    keyword: str
    status: int | None = None
    timeout: int = Field(default=30_000, ge=1)


class HookConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    commands: list[str] = Field(default_factory=list)
    timeout: int = Field(default=30, ge=1)


class HooksConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    on_browser_start: HookConfig | None = None
    on_page_before_goto: HookConfig | None = None
    on_page_after_load: HookConfig | None = None
    on_run_complete: HookConfig | None = None


class PageLifecycleConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    close_after_inspection: bool = True
    clear_network_records: bool = True


class PageConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str | None = None
    url: str
    screenshot: bool = True
    save_html: bool = True
    save_network: bool = True
    wait_ms: int = Field(default=1000, ge=0)
    timeout: int | None = Field(default=None, ge=1)
    retry: RetryConfig | None = None
    lifecycle: PageLifecycleConfig = Field(default_factory=PageLifecycleConfig)
    close_page: bool | None = None  # backward compatible
    hooks: HooksConfig | None = None
    network_middlewares: dict[str, Any] | None = None
    pre_replay_requests: list[ReplayRequestConfig] = Field(default_factory=list)
    replay_requests: list[ReplayRequestConfig] = Field(default_factory=list)
    wait_for_requests: list[WaitRequestConfig] = Field(default_factory=list)
    wait_for_responses: list[WaitResponseConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_lifecycle(self) -> "PageConfig":
        if self.close_page is not None:
            self.lifecycle.close_after_inspection = self.close_page
        return self


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    vars: dict[str, Any] = Field(default_factory=dict)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    hooks: HooksConfig | None = None
    context_middlewares: dict[str, Any] | None = None
    network_middlewares: dict[str, Any] | None = None
    replay_requests: list[ReplayRequestConfig] = Field(default_factory=list)
    pages: list[PageConfig] = Field(default_factory=list)
