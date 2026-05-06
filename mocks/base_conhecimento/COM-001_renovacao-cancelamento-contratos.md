---
id: COM-001
title: "Processo de renovação e cancelamento de contratos"
category: comercial
tags: [renovação, cancelamento, contrato, SLA, churn]
module: comercial
audience: interno
created_at: 2025-02-14
updated_at: 2026-01-20
author: Juliana Martins
---

# Processo de renovação e cancelamento de contratos

## Visão geral

Este artigo descreve o fluxo interno para lidar com tickets de renovação de contrato e solicitações de cancelamento. O time de atendimento é a primeira linha de contato e tem papel fundamental na retenção do cliente antes de qualquer escalação para o time comercial.

---

## Renovação de contrato

### Quando este ticket aparece

- Cliente responde a e-mail automático de aviso de vencimento (60, 30 e 15 dias antes)
- Cliente entra em contato proativamente perguntando sobre condições
- Time comercial solicita abertura de ticket para formalizar tratativa

### Fluxo de atendimento

```
1. Confirmar dados do contrato atual (vigência, plano, valor)
   ↓
2. Verificar histórico de uso e satisfação do cliente
   ↓
3. Identificar se há pendências financeiras em aberto
   ↓
4. Encaminhar para o CSM (Customer Success Manager) responsável
   ↓
5. Registrar retorno no ticket com prazo de 2 dias úteis
```

### Informações necessárias antes de acionar o CSM

- Nome do cliente e ID (`id_cliente`)
- Data de vencimento do contrato atual
- Plano contratado e valor vigente
- Existe interesse em upgrade ou mudança de plano?
- Cliente mencionou algum concorrente ou proposta alternativa?

### Descontos e condições especiais

O atendimento **não tem autonomia** para oferecer descontos. Toda negociação de valor deve passar pelo CSM ou gerência comercial.

> 💡 Se o cliente mencionar proposta de concorrente, registre no ticket e escale com prioridade **alto** para o CSM imediatamente.

---

## Cancelamento de contrato

### Abordagem inicial

Nunca processe um cancelamento sem antes tentar entender o motivo e oferecer alternativas. Use as perguntas abaixo:

1. "Pode me contar o que motivou essa decisão?"
2. "Houve algum problema específico que não conseguimos resolver?"
3. "Existe algo que, se resolvido, mudaria sua decisão?"

### Motivos mais comuns e respostas sugeridas

| Motivo relatado | Ação recomendada |
|---|---|
| Preço muito alto | Acionar CSM para análise de desconto ou downgrade de plano |
| Falta de funcionalidade | Registrar feedback, verificar roadmap, encaminhar para produto |
| Problemas técnicos recorrentes | Escalar para tech lead + comprometer prazo de resolução |
| Troca por concorrente | Escalar imediatamente para gerência comercial |
| Encerramento da empresa | Processar cancelamento e registrar motivo no CRM |

### Fluxo de cancelamento formal

Somente após esgotar as tentativas de retenção:

1. Confirmar identidade e cargo de quem solicita (deve ser representante legal ou responsável pelo contrato)
2. Abrir chamado interno no sistema de contratos com tag `cancelamento`
3. Informar prazo de encerramento conforme cláusula contratual (geralmente 30 dias corridos)
4. Enviar e-mail de confirmação com protocolo
5. Registrar motivo de churn no CRM

---

## SLAs deste tipo de ticket

| Prioridade | Primeiro contato | Resolução |
|---|---|---|
| Baixo | 24h úteis | 5 dias úteis |
| Médio | 8h úteis | 3 dias úteis |
| Alto | 4h úteis | 2 dias úteis |
| Crítico | 1h | Imediato (escalar) |

---

## Escalação

- **CSM responsável pelo cliente**: sempre a primeira escalação
- **Gerência comercial**: quando CSM não obtiver resposta em 24h ou cliente ameaçar cancelamento imediato
- **Diretoria**: apenas em casos de contratos enterprise (acima de R$ 50k/ano) ou ameaça jurídica

---

## Tickets relacionados

- TKT-0033, TKT-0287, TKT-0654, TKT-1102, TKT-1899

---

## Histórico de revisões

| Data | Alteração | Autor |
|---|---|---|
| 2025-02-14 | Criação do artigo | Juliana Martins |
| 2025-07-08 | Atualização do fluxo de cancelamento | Carlos Souza |
| 2026-01-20 | Revisão dos SLAs e adição de tabela de motivos | Juliana Martins |
