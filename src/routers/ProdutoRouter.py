from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import List

# Services
from services.AuditoriaService import AuditoriaService

# Domain Schemas
from domain.schemas.ProdutoSchema import (
    ProdutoCreate,
    ProdutoUpdate,
    ProdutoResponse,
    ProdutoResponsePublico
)
from domain.schemas.AuthSchema import ProdutoAuth

# Infra
from infra.orm.ProdutoModel import ProdutoDB
from infra.database import get_db
from infra.dependencies import get_current_active_user, require_group

router = APIRouter()

# Criar as rotas/endpoints: GET, POST, PUT, DELETE

@router.get("/produto/publico", response_model=List[ProdutoResponsePublico], tags=["Produto"], status_code=status.HTTP_200_OK)
async def get_produto(db: Session = Depends(get_db)):
    """Retorna todos os produtos de forma publica, sem id e sem valor   """
    try:
        produtos = db.query(ProdutoDB).all()
        return produtos

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar produtos: {str(e)}"
        )

@router.get("/produto/", response_model=List[ProdutoResponse], tags=["Produto"], status_code=status.HTTP_200_OK)
async def get_produto(
    request: Request,
    db: Session = Depends(get_db),
    current_user: ProdutoAuth = Depends(get_current_active_user)
):
    """Retorna todos os produtos, autenticado"""
    try:
        produtos = db.query(ProdutoDB).all()
        return produtos

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar produtos: {str(e)}"
        )


@router.get("/produto/{id}", response_model=ProdutoResponse, tags=["Produto"], status_code=status.HTTP_200_OK)
async def get_produto(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    current_user: ProdutoAuth = Depends(get_current_active_user)
):
    """Retorna um produto específico pelo ID, autenticado"""
    try:
        produto = db.query(ProdutoDB).filter(ProdutoDB.id == id).first()

        if not produto:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Produto não encontrado"
            )

        return produto

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar produto: {str(e)}"
        )


@router.post("/produto/", response_model=ProdutoResponse, status_code=status.HTTP_201_CREATED, tags=["Produto"])
async def post_produto(
    request: Request,
    produto_data: ProdutoCreate,
    db: Session = Depends(get_db),
    current_user: ProdutoAuth = Depends(require_group([1]))
):
    """Cria um novo produto, autenticado e grupo 1"""
    try:

        novo_produto = ProdutoDB(
            id=None,
            nome=produto_data.nome,
            descricao=produto_data.descricao,
            foto=produto_data.foto,
            valor_unitario=produto_data.valor_unitario
        )

        db.add(novo_produto)
        db.commit()
        db.refresh(novo_produto)

        # Depois de tudo executado e antes do return, registra a ação na auditoria
        AuditoriaService.registrar_acao(
            db=db,
            funcionario_id=current_user.id,
            acao="CREATE",
            recurso="PRODUTO",
            recurso_id=novo_produto.id,
            dados_antigos=None,
            dados_novos=novo_produto,
            request=request
        )

        return novo_produto

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao criar produto: {str(e)}"
        )


@router.put("/produto/{id}", response_model=ProdutoResponse, tags=["Produto"], status_code=status.HTTP_200_OK)
async def put_produto(
    request: Request,
    id: int,
    produto_data: ProdutoUpdate,
    db: Session = Depends(get_db),
    current_user: ProdutoAuth = Depends(require_group([1]))
):
    """Atualiza um produto existente, precisa estar autenticado e grupo 1"""
    try:
        produto = db.query(ProdutoDB).filter(ProdutoDB.id == id).first()

        if not produto:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Produto não encontrado"
            )

        # armazena uma copia do objeto com os dados atuais, para salvar na auditoria
        # não pode manter referencia com produto, para que o auditoria possa comparar
        # por isso a cópia do __dict__
        dados_antigos_obj = produto.__dict__.copy()

        update_data = produto_data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(produto, field, value)

        db.commit()
        db.refresh(produto)

        # Depois de tudo executado e antes do return, registra a ação na auditoria
        AuditoriaService.registrar_acao(
            db=db,
            funcionario_id=current_user.id,
            acao="UPDATE",
            recurso="PRODUTO",
            recurso_id=produto.id,
            dados_antigos=dados_antigos_obj,
            dados_novos=produto,
            request=request
        )

        return produto

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao atualizar produto: {str(e)}"
        )


@router.delete("/produto/{id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Produto"], summary="Remover produto")
async def delete_produto(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    current_user: ProdutoAuth = Depends(require_group([1]))
):
    """Remove um produto, precisa estar autenticado e grupo 1"""
    try:
        produto = db.query(ProdutoDB).filter(ProdutoDB.id == id).first()

        if not produto:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Produto não encontrado"
            )

        db.delete(produto)
        db.commit()

        # Depois de tudo executado e antes do return, registra a ação na auditoria
        AuditoriaService.registrar_acao(
            db=db,
            funcionario_id=current_user.id,
            acao="DELETE",
            recurso="PRODUTO",
            recurso_id=produto.id,
            dados_antigos=produto,
            dados_novos=None,
            request=request
        )

        return None

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao deletar produto: {str(e)}"
        )