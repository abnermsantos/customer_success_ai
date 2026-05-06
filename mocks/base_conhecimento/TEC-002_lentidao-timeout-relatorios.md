---
id: TEC-002
title: "Lentidão e timeout ao carregar relatórios"
category: técnica
tags: [performance, timeout, relatórios, lentidão, banco-de-dados]
module: relatórios
audience: interno
created_at: 2025-05-22
updated_at: 2026-03-30
author: Felipe Oliveira
---

# Lentidão e timeout ao carregar relatórios

## Descrição do problema

Um dos tickets mais recorrentes da fila técnica. Clientes relatam que relatórios demoram mais de 30 segundos para carregar ou retornam erro de timeout sem exibir dados. O problema tende a se agravar em:

- Final de mês (fechamento financeiro)
- Relatórios com filtros de datas amplos (ex: ano inteiro)
- Ambientes com grande volume de dados (acima de 500k registros)

---

## Diagnóstico

### Perguntas para o cliente

- Qual relatório específico está lento? (nome + módulo)
- Qual o filtro de data utilizado?
- O problema ocorre sempre ou em horários específicos?
- Outros módulos do sistema estão lentos também, ou só relatórios?

### Verificações internas

#### 1. Checar uso de recursos no servidor

Acesse o painel de monitoramento do ambiente do cliente e verifique:

- **CPU**: acima de 80% durante a geração do relatório?
- **Memória**: swapping ativo?
- **Banco de dados**: queries de longa duração rodando em paralelo?

#### 2. Identificar a query problemática

No banco de dados, execute:

```sql
SELECT pid, now() - pg_stat_activity.query_start AS duration, query
FROM pg_stat_activity
WHERE (now() - pg_stat_activity.query_start) > interval '5 seconds'
AND state = 'active';
```

Se houver queries rodando há mais de 30s, copie e compartilhe com o time de DBA.

#### 3. Verificar índices

Relatórios lentos frequentemente indicam falta de índice em colunas de filtro. As mais comuns:

```sql
-- Verificar índices existentes na tabela de transações
SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'transactions';
```

---

## Solução

### Solução imediata (paliativa)

1. Oriente o cliente a **reduzir o intervalo de datas** do filtro (ex: mensal ao invés de anual).
2. Sugira exportar o relatório em background (se disponível): `Relatórios > Agendar exportação`.
3. Se o servidor estiver sobrecarregado, alinhe com a equipe de infra para reiniciar o serviço de relatórios:
   ```bash
   sudo systemctl restart report-service
   ```

### Solução definitiva

| Causa identificada | Ação |
|---|---|
| Query sem índice | Acionar time de DBA para criação de índice |
| Volume excessivo de dados | Habilitar paginação de resultados no relatório |
| Timeout configurado muito baixo | Ajustar `query_timeout` no arquivo de configuração (`config/database.yml`) |
| Concorrência excessiva | Habilitar fila de geração de relatórios assíncrona |

---

## Configuração de timeout recomendada

No arquivo `config/database.yml`, o valor padrão é `30000ms`. Para ambientes com alto volume:

```yaml
database:
  query_timeout: 120000  # 2 minutos
  pool_size: 10
```

> ⚠️ Alterações de configuração requerem aprovação do time de infra antes de aplicar em produção.

---

## Escalação

Escale para o time de DBA se:
- A query problemática estiver identificada mas não houver índice adequado
- O volume de dados ultrapassar 1 milhão de registros na tabela afetada
- O problema persistir após reinicialização do serviço

---

## Tickets relacionados

- TKT-0145, TKT-0412, TKT-0989, TKT-1567, TKT-2201

---

## Histórico de revisões

| Data | Alteração | Autor |
|---|---|---|
| 2025-05-22 | Criação do artigo | Felipe Oliveira |
| 2025-11-15 | Adicionada query de diagnóstico SQL | Diego Ferreira |
| 2026-03-30 | Atualização da config de timeout recomendada | Felipe Oliveira |
