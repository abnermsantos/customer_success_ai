---
id: FIN-002
title: "Cobranças duplicadas, reembolsos e conciliação financeira"
category: financeira
tags: [cobrança-duplicada, reembolso, conciliação, estorno, fatura]
module: financeiro
audience: interno
created_at: 2025-03-25
updated_at: 2026-03-14
author: Patrícia Nunes
---

# Cobranças duplicadas, reembolsos e conciliação financeira

## Visão geral

Este artigo cobre três situações financeiras sensíveis que exigem atenção e cuidado no atendimento: cobranças indevidas, solicitações de reembolso e inconsistências em relatórios de conciliação. Todos envolvem impacto financeiro direto para o cliente e devem ser tratados com prioridade.

---

## Cobranças duplicadas

### Como identificar

- Cliente relata ter pago duas vezes o mesmo boleto
- Extrato do cliente mostra dois débitos no mesmo valor em datas próximas
- Sistema mostra dois registros de pagamento para a mesma competência

### Procedimento de verificação

1. Acesse `Financeiro > Cobranças > [id_cliente]` e filtre pelo período relatado
2. Confirme se há dois registros de pagamento com o mesmo valor e competência
3. Verifique a origem de cada pagamento (banco X, banco Y, cartão etc.)
4. Solicite comprovante(s) de pagamento ao cliente

> ⚠️ Nunca confirme a duplicidade apenas com base no relato do cliente. Sempre valide nos registros internos antes de qualquer ação.

### Ação após confirmação

| Situação | Ação |
|---|---|
| Duplicidade confirmada, pagamento via boleto | Emitir crédito para próxima fatura OU processar reembolso |
| Duplicidade confirmada, pagamento via cartão | Solicitar estorno ao gateway de pagamento |
| Duplicidade não confirmada | Explicar ao cliente e apresentar os registros de pagamento |

---

## Reembolsos

### Política de reembolso (resumo para atendimento)

- Reembolsos são processados em até **10 dias úteis** após aprovação
- O atendimento **não tem autonomia** para aprovar reembolsos — toda solicitação precisa de aprovação do time financeiro
- Reembolsos acima de **R$ 1.000** requerem aprovação da gerência financeira

### Fluxo de solicitação

```
1. Registrar motivo detalhado no ticket
   ↓
2. Anexar comprovante(s) de pagamento enviado(s) pelo cliente
   ↓
3. Escalar ticket para o time financeiro com tag "reembolso"
   ↓
4. Aguardar aprovação (prazo: 2 dias úteis)
   ↓
5. Após aprovação, informar cliente sobre prazo e forma de devolução
   ↓
6. Registrar no ticket a confirmação de processamento
```

### Formas de devolução

| Forma de pagamento original | Forma de devolução preferencial |
|---|---|
| Boleto bancário | PIX ou TED para conta indicada pelo cliente |
| Cartão de crédito | Estorno no cartão (pode levar até 2 faturas) |
| PIX | PIX para a chave de origem |

> 💡 Sempre confirme os dados bancários do cliente por escrito no ticket antes de processar qualquer devolução.

---

## Conciliação financeira

### Quando este ticket aparece

- Cliente relata que o relatório de faturamento não bate com os pagamentos recebidos
- Divergência entre o que foi cobrado e o que consta no sistema do cliente (ERP)
- Valores de relatório interno diferentes dos extratos bancários

### Diagnóstico

1. Solicite ao cliente o período exato e o relatório/extrato com as divergências
2. Exporte o mesmo período pelo sistema interno: `Relatórios > Financeiro > Extrato de Cobranças`
3. Compare linha a linha os registros (pode ser feito em planilha)
4. As causas mais comuns são:

| Causa | Explicação |
|---|---|
| Diferença de fuso horário | Pagamentos próximos à meia-noite podem cair em dias diferentes |
| Taxa de gateway não deduzida | Valor líquido ≠ valor bruto cobrado |
| Estorno não refletido | Estorno processado mas não sincronizado no relatório |
| Pagamento manual não registrado | Pagamento feito fora do sistema (ex: transferência direta) |

### Ação por tipo de divergência

- **Fuso horário**: ajustar filtro de data e reexportar relatório
- **Taxa de gateway**: explicar a dedução e, se necessário, ativar coluna "valor líquido" no relatório
- **Estorno pendente**: verificar status do estorno no painel do gateway e aguardar sincronização (pode levar até 3 dias úteis)
- **Pagamento manual**: registrar o pagamento manualmente em `Financeiro > Cobranças > Registrar Pagamento Manual`

---

## Escalação

- **Time financeiro**: qualquer reembolso, cobrança duplicada confirmada ou divergência acima de R$ 500
- **Gerência financeira**: reembolsos acima de R$ 1.000 ou situações com risco jurídico (cliente menciona ação legal)
- **Time técnico**: se a divergência parecer ser bug no cálculo ou sincronização do sistema

---

## Tickets relacionados

- TKT-0178, TKT-0503, TKT-0991, TKT-1678, TKT-2445, TKT-3890

---

## Histórico de revisões

| Data | Alteração | Autor |
|---|---|---|
| 2025-03-25 | Criação do artigo | Patrícia Nunes |
| 2025-09-10 | Adicionada seção de conciliação financeira | Roberto Alves |
| 2026-03-14 | Atualização da política de reembolso (novo limite R$1k) | Patrícia Nunes |
