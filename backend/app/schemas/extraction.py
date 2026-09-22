"""Structured-output schemas for Gemini document extraction (Phase 3).

Every top-level scalar field is wrapped in an Extracted* envelope carrying a
per-field confidence (0-1) and a `legible` flag, per CLAUDE.md rule 3/8: the LLM
fills a strict schema, nothing more, and low-confidence/illegible fields must be
visible to the fraud layer (Phase 4) and the completeness gate (Phase 5) rather
than silently defaulting.

Nested row-level data (weekly earnings rows, bill line items, payment-history
rows) is intentionally NOT individually confidence-wrapped: a whole extracted
table is already gated by the parent document's overall extraction_confidence
(see ExtractionResult in llm_client.py), and a per-cell confidence/legible pair
on every row field would make prompts and schemas unwieldy for no decision the
policy engine (Phase 5) actually makes at that granularity. Documented in
docs/PROGRESS.md as a deliberate scope decision, not an oversight.

Every value is `None` (never guessed) when the source document doesn't show it,
per the prompt's own instruction to the model.
"""

from pydantic import BaseModel, Field


class ExtractedStr(BaseModel):
    value: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    legible: bool


class ExtractedFloat(BaseModel):
    value: float | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    legible: bool


class ExtractedInt(BaseModel):
    value: int | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    legible: bool


class ExtractedDate(BaseModel):
    """`value` is an ISO-8601 date string (YYYY-MM-DD), never a Python date --
    keeps the JSON schema handed to Gemini a plain string, and validation of
    "is this actually a real, plausible date" happens explicitly in
    app/services/extraction/guardrails.py rather than being silently coerced."""

    value: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    legible: bool


class GigPayoutWeek(BaseModel):
    week_start: str
    week_end: str
    active_days: int
    trips_or_orders: int
    gross_earnings: float
    incentives: float
    deductions: float
    net_payout: float


class GigPayoutExtraction(BaseModel):
    platform_name: ExtractedStr
    partner_name: ExtractedStr
    partner_id: ExtractedStr
    partner_since: ExtractedDate
    report_period_start: ExtractedDate
    report_period_end: ExtractedDate
    weeks: list[GigPayoutWeek]
    total_net_payout_period: ExtractedFloat
    payout_account_last4: ExtractedStr
    suspected_instruction_text: bool


class UtilityLineItem(BaseModel):
    label: str
    amount: float


class UtilityPaymentHistoryRow(BaseModel):
    month: str
    amount: float
    due_date: str
    paid_date: str | None = None
    status: str


class UtilityBillExtraction(BaseModel):
    utility_name: ExtractedStr
    consumer_name: ExtractedStr
    consumer_number: ExtractedStr
    service_address: ExtractedStr
    connection_date: ExtractedDate
    meter_number: ExtractedStr
    bill_date: ExtractedDate
    due_date: ExtractedDate
    billing_period_start: ExtractedDate
    billing_period_end: ExtractedDate
    units_consumed: ExtractedInt
    line_items: list[UtilityLineItem]
    total_amount_due: ExtractedFloat
    payment_history: list[UtilityPaymentHistoryRow]
    suspected_instruction_text: bool


EXTRACTION_SCHEMAS: dict[str, type[BaseModel]] = {
    "GIG_PAYOUT": GigPayoutExtraction,
    "UTILITY_BILL": UtilityBillExtraction,
}


class GigPayoutExtractionPermuted(BaseModel):
    total_net_payout_period: ExtractedFloat
    payout_account_last4: ExtractedStr
    weeks: list[GigPayoutWeek]
    report_period_end: ExtractedDate
    report_period_start: ExtractedDate
    partner_since: ExtractedDate
    partner_id: ExtractedStr
    partner_name: ExtractedStr
    platform_name: ExtractedStr
    suspected_instruction_text: bool

    def to_canonical(self) -> GigPayoutExtraction:
        return GigPayoutExtraction.model_validate(self.model_dump())


class UtilityBillExtractionPermuted(BaseModel):
    total_amount_due: ExtractedFloat
    units_consumed: ExtractedInt
    payment_history: list[UtilityPaymentHistoryRow]
    line_items: list[UtilityLineItem]
    billing_period_end: ExtractedDate
    billing_period_start: ExtractedDate
    due_date: ExtractedDate
    bill_date: ExtractedDate
    meter_number: ExtractedStr
    connection_date: ExtractedDate
    service_address: ExtractedStr
    consumer_number: ExtractedStr
    consumer_name: ExtractedStr
    utility_name: ExtractedStr
    suspected_instruction_text: bool

    def to_canonical(self) -> UtilityBillExtraction:
        return UtilityBillExtraction.model_validate(self.model_dump())


EXTRACTION_SCHEMAS_PERMUTED: dict[str, type[BaseModel]] = {
    "GIG_PAYOUT": GigPayoutExtractionPermuted,
    "UTILITY_BILL": UtilityBillExtractionPermuted,
}
