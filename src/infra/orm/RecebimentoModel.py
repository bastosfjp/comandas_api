from sqlalchemy import Column, Integer, DECIMAL, DateTime, ForeignKey
from infra.database import Base


class RecebimentoDB(Base):
    """Transação de recebimento (pagamento) realizada no caixa.
    Pode quitar uma ou várias comandas em uma única operação."""
    __tablename__ = "tb_recebimento"
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    funcionario_id = Column(Integer, ForeignKey("tb_funcionario.id", ondelete="RESTRICT"), nullable=False)  # quem recebeu
    cliente_id = Column(Integer, ForeignKey("tb_cliente.id", ondelete="RESTRICT"), nullable=True, default=None)  # cliente, se informado
    subtotal = Column(DECIMAL(10, 2), nullable=False)  # soma das comandas, antes de desconto/acréscimo
    desconto_valor = Column(DECIMAL(10, 2), nullable=False, default=0)
    acrescimo_valor = Column(DECIMAL(10, 2), nullable=False, default=0)
    valor_final = Column(DECIMAL(10, 2), nullable=False)  # subtotal - desconto + acréscimo
    data_hora = Column(DateTime, nullable=False)


class RecebimentoComandaDB(Base):
    """Vínculo entre um recebimento e cada comanda quitada nele (N:N)."""
    __tablename__ = "tb_recebimento_comanda"
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    recebimento_id = Column(Integer, ForeignKey("tb_recebimento.id", ondelete="RESTRICT"), nullable=False)
    comanda_id = Column(Integer, ForeignKey("tb_comanda.id", ondelete="RESTRICT"), nullable=False)
    subtotal = Column(DECIMAL(10, 2), nullable=False)  # valor desta comanda na transação