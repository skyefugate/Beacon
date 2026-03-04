"""Fault domain models for classifying where network problems originate.

The fault domain hierarchy follows the network path from the user's device
outward: device → wifi → LAN → ISP → DNS → app/SaaS → VPN/SASE.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class FaultDomain(str, Enum):
    DEVICE = "device"
    WIFI = "wifi"
    LAN = "lan"
    ISP = "isp"
    DNS = "dns"
    APP_SAAS = "app_saas"
    VPN_SASE = "vpn_sase"
    UNKNOWN = "unknown"


class CompetingHypothesis(BaseModel):
    """An alternative fault domain that was considered but scored lower."""

    fault_domain: FaultDomain
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class FaultDomainResult(BaseModel):
    """The engine's conclusion about where the problem lies.

    confidence is 0.0–1.0. evidence_refs point to specific metrics,
    test results, or events that support the conclusion.
    """

    fault_domain: FaultDomain
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_refs: list[str] = Field(default_factory=list)
    competing_hypotheses: list[CompetingHypothesis] = Field(default_factory=list)
