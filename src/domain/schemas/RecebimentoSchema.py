from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Any, Dict
from datetime import datetime
from domain.schemas.FuncionarioSchema import FuncionarioResponse
from domain.schemas.ClienteSchema import ClienteResponse


# ===========================================================================================================
# DASHBOARD - lista simplificada das comandas abertas (produtos aparecem no detalhe)
# ===========================================================================================================
class RecebimentoDashboardItem(BaseModel):
    """Item do dashboard simplificado - produtos são mostrados no detalhe."""
    id: int
    comanda: str
    status: int
    cliente: Optional[ClienteResponse] = None
    total: float
    quantidade_produtos: int
    data_hora: datetime


# ===========================================================================================================
# DETALHE - comandas com seus produtos (foto, quantidade, valor) para conferência do cliente
# ===========================================================================================================
class ItemComandaDetalhe(BaseModel):
    """Produto consumido em uma comanda, com foto e subtotal."""
    produto_id: int
    nome: str
    foto: Optional[bytes] = None  # data URL base64 (obrigatório exibir na recuperação)
    quantidade: int
    valor_unitario: float
    subtotal: float


class ComandaDetalhe(BaseModel):
    """Detalhe de uma comanda para conferência no caixa."""
    id: int
    comanda: str
    status: int
    data_hora: datetime
    cliente: Optional[ClienteResponse] = None
    funcionario: Optional[FuncionarioResponse] = None
    itens: List[ItemComandaDetalhe]
    quantidade_produtos: int
    total: float


class RecebimentoDetalheResponse(BaseModel):
    """Conjunto de comandas selecionadas para recebimento (permite múltiplas)."""
    comandas: List[ComandaDetalhe]
    quantidade_comandas: int
    total_geral: float


# ===========================================================================================================
# RECEBIMENTO COMPLETO - processa o pagamento de uma ou mais comandas numa única operação
# ===========================================================================================================
class RecebimentoCompletoRequest(BaseModel):
    """Request completa para recebimento com desconto/acréscimo por valor."""
    comandas_ids: List[int]
    cliente_id: Optional[int] = None
    funcionario_id: int
    desconto_valor: Optional[float] = None
    acrescimo_valor: Optional[float] = None


class ComandaPaga(BaseModel):
    """Resumo de uma comanda quitada no recebimento."""
    id: int
    comanda: str
    subtotal: float


class RecebimentoCompletoResponse(BaseModel):
    """Response completa do recebimento realizado."""
    sucesso: bool
    mensagem: str
    recebimento_id: int
    comandas_pagas: List[ComandaPaga]
    subtotal_geral: float
    desconto_total: float
    acrescimo_total: float
    valor_final: float
    cliente: Optional[ClienteResponse] = None
    funcionario: FuncionarioResponse
    data_hora: datetime


# ===========================================================================================================
# COMPROVANTE - detalhamento do recebimento (comandas quitadas)
# ===========================================================================================================
class ComprovanteRecebimento(BaseModel):
    """Comprovante detalhado do recebimento."""
    model_config = ConfigDict(from_attributes=True)
    cabecalho: Dict[str, Any]
    cliente: Optional[Dict[str, Any]] = None
    funcionario: Dict[str, Any]
    comandas: List[Dict[str, Any]]
    resumo_valores: Dict[str, Any]
    recebimento: Dict[str, Any]
    rodape: Dict[str, Any]
    data_emissao: datetime