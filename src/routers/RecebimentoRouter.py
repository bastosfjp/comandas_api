from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List
from datetime import datetime

from domain.schemas.RecebimentoSchema import (
    RecebimentoDashboardItem,
    RecebimentoDetalheResponse, ComandaDetalhe, ItemComandaDetalhe,
    RecebimentoCompletoRequest, RecebimentoCompletoResponse, ComandaPaga,
    ComprovanteRecebimento,
)
from domain.schemas.FuncionarioSchema import FuncionarioResponse
from domain.schemas.ClienteSchema import ClienteResponse
from domain.schemas.AuthSchema import FuncionarioAuth

from infra.orm.ComandaModel import ComandaDB, ComandaProdutoDB
from infra.orm.ProdutoModel import ProdutoDB
from infra.orm.FuncionarioModel import FuncionarioDB
from infra.orm.ClienteModel import ClienteDB
from infra.orm.RecebimentoModel import RecebimentoDB, RecebimentoComandaDB
from infra.database import get_async_db
from infra.dependencies import get_current_active_user, require_group
from infra.rate_limit import limiter, get_rate_limit
from services.AuditoriaService import AuditoriaService

router = APIRouter()

STATUS_ABERTA = 0
STATUS_FECHADA = 1


# ===========================================================================================================
# Helpers
# ===========================================================================================================
def _foto_to_str(foto):
    """A foto é armazenada como data URL base64 (bytes utf-8). Devolve string para o front."""
    if foto is None:
        return None
    if isinstance(foto, (bytes, bytearray)):
        try:
            return foto.decode("utf-8")
        except Exception:
            return None
    return str(foto)


async def _carregar_itens(db: AsyncSession, comanda_id: int):
    """Retorna (lista_de_ItemComandaDetalhe, quantidade_total, total) de uma comanda."""
    query = (
        select(ComandaProdutoDB, ProdutoDB)
        .outerjoin(ProdutoDB, ComandaProdutoDB.produto_id == ProdutoDB.id)
        .where(ComandaProdutoDB.comanda_id == comanda_id)
    )
    rows = (await db.execute(query)).all()
    itens = []
    quantidade_total = 0
    total = 0.0
    for cp, produto in rows:
        valor_unitario = float(cp.valor_unitario)
        subtotal = round(valor_unitario * cp.quantidade, 2)
        total += subtotal
        quantidade_total += cp.quantidade
        itens.append(ItemComandaDetalhe(
            produto_id=cp.produto_id,
            nome=produto.nome if produto else "Produto removido",
            foto=_foto_to_str(produto.foto) if produto else None,
            quantidade=cp.quantidade,
            valor_unitario=valor_unitario,
            subtotal=subtotal,
        ))
    return itens, quantidade_total, round(total, 2)


# ===========================================================================================================
# GET /recebimento/dashboard - dashboard completo com comandas abertas
# ===========================================================================================================
@router.get("/recebimento/dashboard", response_model=List[RecebimentoDashboardItem], tags=["Recebimento"], summary="Dashboard completo com comandas abertas e fotos - protegida por JWT")
@limiter.limit(get_rate_limit("moderate"))
async def get_dashboard(request: Request, db: AsyncSession = Depends(get_async_db), current_user: FuncionarioAuth = Depends(get_current_active_user)):
    try:
        # Totais (valor e quantidade) por comanda, em uma única query agregada
        totais_query = (
            select(
                ComandaProdutoDB.comanda_id,
                func.coalesce(func.sum(ComandaProdutoDB.quantidade * ComandaProdutoDB.valor_unitario), 0).label("total"),
                func.coalesce(func.sum(ComandaProdutoDB.quantidade), 0).label("qtd"),
            )
            .group_by(ComandaProdutoDB.comanda_id)
        )
        totais = {row.comanda_id: (float(row.total), int(row.qtd)) for row in (await db.execute(totais_query)).all()}

        # Comandas abertas, com cliente
        comandas_query = (
            select(ComandaDB, ClienteDB)
            .outerjoin(ClienteDB, ClienteDB.id == ComandaDB.cliente_id)
            .where(ComandaDB.status == STATUS_ABERTA)
            .order_by(ComandaDB.data_hora.asc())
        )
        rows = (await db.execute(comandas_query)).all()

        dashboard = []
        for comanda, cliente in rows:
            total, qtd = totais.get(comanda.id, (0.0, 0))
            dashboard.append(RecebimentoDashboardItem(
                id=comanda.id,
                comanda=comanda.comanda,
                status=comanda.status,
                cliente=ClienteResponse(id=cliente.id, nome=cliente.nome, cpf=cliente.cpf, telefone=cliente.telefone) if cliente else None,
                total=round(total, 2),
                quantidade_produtos=qtd,
                data_hora=comanda.data_hora,
            ))
        return dashboard
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Erro ao montar dashboard: {str(e)}")


# ===========================================================================================================
# GET /recebimento/comandas/detalhe/{comandas_ids} - detalhar comandas para recebimento
# comandas_ids: lista separada por vírgula, ex: "1,2,3"
# ===========================================================================================================
@router.get("/recebimento/comandas/detalhe/{comandas_ids}", response_model=RecebimentoDetalheResponse, tags=["Recebimento"], summary="Detalhar comandas para recebimento (uma ou mais) - protegida por JWT")
@limiter.limit(get_rate_limit("moderate"))
async def get_detalhe(comandas_ids: str, request: Request, db: AsyncSession = Depends(get_async_db), current_user: FuncionarioAuth = Depends(get_current_active_user)):
    try:
        # Parse dos ids "1,2,3"
        try:
            ids = [int(x) for x in comandas_ids.split(",") if x.strip() != ""]
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="IDs de comandas inválidos. Use números separados por vírgula, ex: 1,2,3")
        if not ids:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Informe ao menos uma comanda")

        comandas_detalhe = []
        total_geral = 0.0
        for comanda_id in ids:
            query = (
                select(ComandaDB, FuncionarioDB, ClienteDB)
                .outerjoin(FuncionarioDB, FuncionarioDB.id == ComandaDB.funcionario_id)
                .outerjoin(ClienteDB, ClienteDB.id == ComandaDB.cliente_id)
                .where(ComandaDB.id == comanda_id)
            )
            row = (await db.execute(query)).first()
            if not row:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Comanda {comanda_id} não encontrada")
            comanda, funcionario, cliente = row

            itens, qtd, total = await _carregar_itens(db, comanda.id)
            total_geral += total

            comandas_detalhe.append(ComandaDetalhe(
                id=comanda.id,
                comanda=comanda.comanda,
                status=comanda.status,
                data_hora=comanda.data_hora,
                cliente=ClienteResponse(id=cliente.id, nome=cliente.nome, cpf=cliente.cpf, telefone=cliente.telefone) if cliente else None,
                funcionario=FuncionarioResponse(id=funcionario.id, nome=funcionario.nome, matricula=funcionario.matricula, cpf=funcionario.cpf, telefone=funcionario.telefone, grupo=funcionario.grupo) if funcionario else None,
                itens=itens,
                quantidade_produtos=qtd,
                total=total,
            ))

        return RecebimentoDetalheResponse(
            comandas=comandas_detalhe,
            quantidade_comandas=len(comandas_detalhe),
            total_geral=round(total_geral, 2),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Erro ao detalhar comandas: {str(e)}")


# ===========================================================================================================
# POST /recebimento/completo - recebimento completo com desconto/acréscimo (uma única operação)
# ===========================================================================================================
@router.post("/recebimento/completo", response_model=RecebimentoCompletoResponse, status_code=status.HTTP_201_CREATED, tags=["Recebimento"], summary="Recebimento completo com desconto/acréscimo - protegida por JWT")
@limiter.limit(get_rate_limit("restrictive"))
async def post_recebimento_completo(dados: RecebimentoCompletoRequest, request: Request, db: AsyncSession = Depends(get_async_db), current_user: FuncionarioAuth = Depends(get_current_active_user)):
    try:
        if not dados.comandas_ids:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Informe ao menos uma comanda para recebimento")

        # remove duplicados preservando ordem
        comandas_ids = list(dict.fromkeys(dados.comandas_ids))

        # valida funcionário responsável pelo recebimento
        funcionario = (await db.execute(select(FuncionarioDB).where(FuncionarioDB.id == dados.funcionario_id))).scalar_one_or_none()
        if not funcionario:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Funcionário responsável não encontrado")

        # valida cliente, se informado
        cliente = None
        if dados.cliente_id:
            cliente = (await db.execute(select(ClienteDB).where(ClienteDB.id == dados.cliente_id))).scalar_one_or_none()
            if not cliente:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cliente informado não encontrado")

        # carrega e valida cada comanda (deve existir e estar ABERTA)
        comandas = []
        subtotal_geral = 0.0
        for comanda_id in comandas_ids:
            comanda = (await db.execute(select(ComandaDB).where(ComandaDB.id == comanda_id))).scalar_one_or_none()
            if not comanda:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Comanda {comanda_id} não encontrada")
            if comanda.status != STATUS_ABERTA:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Comanda {comanda.comanda} não está aberta (status {comanda.status}) e não pode ser recebida")
            _, _, total = await _carregar_itens(db, comanda.id)
            subtotal_geral += total
            comandas.append((comanda, round(total, 2)))

        subtotal_geral = round(subtotal_geral, 2)

        # desconto/acréscimo
        desconto_total = round(float(dados.desconto_valor or 0), 2)
        acrescimo_total = round(float(dados.acrescimo_valor or 0), 2)
        if desconto_total < 0 or acrescimo_total < 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Desconto e acréscimo não podem ser negativos")
        if desconto_total > subtotal_geral + acrescimo_total:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Desconto não pode ser maior que o valor total")

        valor_final = round(subtotal_geral - desconto_total + acrescimo_total, 2)
        agora = datetime.now()

        # cria a transação de recebimento
        recebimento = RecebimentoDB(
            funcionario_id=funcionario.id,
            cliente_id=cliente.id if cliente else None,
            subtotal=subtotal_geral,
            desconto_valor=desconto_total,
            acrescimo_valor=acrescimo_total,
            valor_final=valor_final,
            data_hora=agora,
        )
        db.add(recebimento)
        await db.flush()  # garante recebimento.id

        comandas_pagas = []
        for comanda, total in comandas:
            # vínculo recebimento <-> comanda
            db.add(RecebimentoComandaDB(recebimento_id=recebimento.id, comanda_id=comanda.id, subtotal=total))
            # atualização da comanda: fecha, registra funcionário do recebimento e ajusta cliente se informado
            comanda.status = STATUS_FECHADA
            comanda.funcionario_id = funcionario.id
            if cliente:
                comanda.cliente_id = cliente.id
            comandas_pagas.append(ComandaPaga(id=comanda.id, comanda=comanda.comanda, subtotal=total))

        await db.commit()
        await db.refresh(recebimento)

        # auditoria (não bloqueia o fluxo se falhar)
        AuditoriaService.registrar_acao(db=db, funcionario_id=current_user.id, acao="CREATE", recurso="RECEBIMENTO", recurso_id=recebimento.id, dados_novos={"comandas": comandas_ids, "valor_final": valor_final}, request=request)

        return RecebimentoCompletoResponse(
            sucesso=True,
            mensagem=f"Recebimento realizado com sucesso. {len(comandas_pagas)} comanda(s) quitada(s).",
            recebimento_id=recebimento.id,
            comandas_pagas=comandas_pagas,
            subtotal_geral=subtotal_geral,
            desconto_total=desconto_total,
            acrescimo_total=acrescimo_total,
            valor_final=valor_final,
            cliente=ClienteResponse(id=cliente.id, nome=cliente.nome, cpf=cliente.cpf, telefone=cliente.telefone) if cliente else None,
            funcionario=FuncionarioResponse(id=funcionario.id, nome=funcionario.nome, matricula=funcionario.matricula, cpf=funcionario.cpf, telefone=funcionario.telefone, grupo=funcionario.grupo),
            data_hora=agora,
        )
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Erro ao processar recebimento: {str(e)}")


# ===========================================================================================================
# GET /recebimento/comprovante/{recebimento_id} - gerar comprovante de recebimento
# ===========================================================================================================
@router.get("/recebimento/comprovante/{recebimento_id}", response_model=ComprovanteRecebimento, tags=["Recebimento"], summary="Gerar comprovante de recebimento - protegida por JWT")
@limiter.limit(get_rate_limit("moderate"))
async def get_comprovante(recebimento_id: int, request: Request, db: AsyncSession = Depends(get_async_db), current_user: FuncionarioAuth = Depends(get_current_active_user)):
    try:
        # recebimento + funcionário + cliente
        query = (
            select(RecebimentoDB, FuncionarioDB, ClienteDB)
            .outerjoin(FuncionarioDB, FuncionarioDB.id == RecebimentoDB.funcionario_id)
            .outerjoin(ClienteDB, ClienteDB.id == RecebimentoDB.cliente_id)
            .where(RecebimentoDB.id == recebimento_id)
        )
        row = (await db.execute(query)).first()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recebimento não encontrado")
        recebimento, funcionario, cliente = row

        # comandas quitadas neste recebimento
        vinculos_query = (
            select(RecebimentoComandaDB, ComandaDB)
            .outerjoin(ComandaDB, ComandaDB.id == RecebimentoComandaDB.comanda_id)
            .where(RecebimentoComandaDB.recebimento_id == recebimento_id)
        )
        vinculos = (await db.execute(vinculos_query)).all()

        comandas_comprovante = []
        for vinculo, comanda in vinculos:
            itens, qtd, total = await _carregar_itens(db, comanda.id)
            comandas_comprovante.append({
                "id": comanda.id,
                "comanda": comanda.comanda,
                "quantidade_produtos": qtd,
                "subtotal": float(vinculo.subtotal),
                "itens": [
                    {
                        "produto_id": it.produto_id,
                        "nome": it.nome,
                        "quantidade": it.quantidade,
                        "valor_unitario": it.valor_unitario,
                        "subtotal": it.subtotal,
                    } for it in itens
                ],
            })

        comprovante = ComprovanteRecebimento(
            cabecalho={
                "titulo": "COMPROVANTE DE RECEBIMENTO",
                "estabelecimento": "Comandas do Zé",
                "recebimento_id": recebimento.id,
            },
            cliente={"id": cliente.id, "nome": cliente.nome, "cpf": cliente.cpf, "telefone": cliente.telefone} if cliente else None,
            funcionario={"id": funcionario.id, "nome": funcionario.nome, "matricula": funcionario.matricula} if funcionario else {},
            comandas=comandas_comprovante,
            resumo_valores={
                "subtotal": float(recebimento.subtotal),
                "desconto": float(recebimento.desconto_valor),
                "acrescimo": float(recebimento.acrescimo_valor),
                "valor_final": float(recebimento.valor_final),
            },
            recebimento={
                "id": recebimento.id,
                "quantidade_comandas": len(comandas_comprovante),
                "data_hora": recebimento.data_hora.isoformat() if recebimento.data_hora else None,
            },
            rodape={
                "mensagem": "Obrigado pela preferência!",
                "emitido_por": current_user.nome,
            },
            data_emissao=datetime.now(),
        )
        return comprovante
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Erro ao gerar comprovante: {str(e)}")
