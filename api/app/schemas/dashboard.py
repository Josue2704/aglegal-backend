from pydantic import BaseModel


class MonthlyMetrics(BaseModel):
    clients_attended: int
    sessions_total: int
    sessions_finalized: int
    incomes: float
    expenses: float
    balance: float
    categories_total: int


class CashflowTotals(BaseModel):
    total_incomes: float
    total_expenses: float
    total_costs: float
    balance: float


class MonthlyPoint(BaseModel):
    month: str
    incomes: float
    expenses: float


class TopItem(BaseModel):
    name: str
    amount: float


class GrossProfitItem(BaseModel):
    name: str
    revenue: float
    cost: float
    gross_profit: float
