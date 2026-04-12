from typing import Optional
from pydantic import BaseModel, Field

class Shipment(BaseModel):
    """
    Pydantic model representing a shipment in the supply chain lifecycle.
    """
    shipment_id: str
    origin: str
    destination: str
    current_node: str = ""
    cargo_type: str = "general"
    priority_tier: int = Field(default=3, ge=1, le=3, description="1 (high), 2 (medium), 3 (low)")
    sla_deadline: Optional[str] = None
    estimated_arrival: Optional[str] = None
    carrier_id: Optional[str] = None
    status: str = Field(default="in_transit", pattern="^(in_transit|delayed|delivered)$")
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)

    class Config:
        from_attributes = True


class Carrier(BaseModel):
    """
    Pydantic model representing a transportation carrier entity.
    """
    carrier_id: str
    carrier_name: str
    reliability_score: float = Field(default=1.0, description="Carrier reliability score")
    active_lanes: str = ""  # Comma-separated list of active lane IDs

    class Config:
        from_attributes = True


class TradeLane(BaseModel):
    """
    Pydantic model representing a generic supply chain trade lane connecting ports.
    """
    lane_id: str
    origin_port: str
    destination_port: str
    mode: str = Field(default="sea", pattern="^(sea|rail|air|road)$")
    base_transit_days: int = Field(default=0, ge=0)
    congestion_index: float = Field(default=0.0, ge=0.0)
    weather_risk: float = Field(default=0.0, ge=0.0)
    geopolitical_score: float = Field(default=0.0, ge=0.0)

    class Config:
        from_attributes = True


class RouteGraphEdge(BaseModel):
    """
    Pydantic model representing an edge in the physical supply chain routing graph.
    """
    edge_id: str
    from_node: str
    to_node: str
    mode: str = "sea"
    distance_km: float = Field(default=0.0, ge=0.0)
    base_transit_days: int = Field(default=0, ge=0)
    congestion_index: float = Field(default=0.0, ge=0.0)
    weather_risk: float = Field(default=0.0, ge=0.0)
    geopolitical_score: float = Field(default=0.0, ge=0.0)
    edge_risk_score: float = Field(default=0.0, ge=0.0)

    class Config:
        from_attributes = True


class DisruptionEvent(BaseModel):
    """
    Pydantic model representing a specific supply chain disruption occurrence.
    """
    event_id: str
    affected_node: str
    disruption_type: str
    severity: float = Field(default=0.0, ge=0.0)
    timestamp: Optional[str] = None
    affected_shipment_count: int = Field(default=0, ge=0)

    class Config:
        from_attributes = True


class RiskBreakdown(BaseModel):
    """
    Pydantic model detailing the breakdown of aggregated risk associated with a given shipment.
    """
    shipment_id: str
    congestion_contribution: float = 0.0
    weather_contribution: float = 0.0
    geopolitical_contribution: float = 0.0
    carrier_reliability_contribution: float = 0.0
    time_pressure_contribution: float = 0.0
    total_risk_score: float = 0.0
    summary_text: str = ""

    class Config:
        from_attributes = True
