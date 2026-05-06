---
id: FIN-001
title: "Erros na emissão de boletos e notas fiscais"
category: financeira
tags: [boleto, nota-fiscal, faturamento, gateway, emissão]
module: financeiro
audience: interno
created_at: 2025-01-18
updated_at: 2026-04-05
author: Roberto Alves
---

# Erros na emissão de boletos e notas fiscais

## Descrição do problema

Tickets financeiros relacionados a falhas na emissão de boletos e notas fiscais são recorrentes, especialmente nos primeiros dias do mês (período de fechamento e faturamento). Os erros mais comuns incluem:

- Boleto gerado sem código de barras válido
- NF-e rejeitada pela SEFAZ
- Nota fiscal emitida com dados incorretos (CNPJ, endereço, valor)
- Boleto enviado por e-mail mas não entregue ao cliente
- Erro 500 ao tentar emitir pelo painel

---

## Diagnóstico

### Perguntas iniciais para o cliente

1. O erro ocorre para todos os clientes/contratos ou apenas um específico?
2. Qual é a mensagem de erro exibida (print ou texto exato)?
3. O boleto/NF chegou a ser gerado mas com dados errados, ou não gerou nada?
4. O problema é novo ou já ocorria antes?

### Verificações internas

#### Para boletos

| Verificação | Onde checar |
|---|---|
| Status da integração com o banco | `Admin > Integrações > Gateway Bancário` |
| Log de geração do boleto | `/var/log/app/billing.log` |
| Validade do certificado bancário | Painel do banco ou arquivo `.crt` do servidor |
| Dados cadastrais do cliente | `Admin > Clientes > [id_cliente] > Dados Financeiros` |

#### Para notas fiscais

| Verificação | Onde checar |
|---|---|
| Retorno da SEFAZ | Log em `/var/log/app/nfe.log` — procurar por código de rejeição |
| Dados do emitente (nossa empresa) | `Admin > Configurações Fiscais > Emitente` |
| Dados do destinatário | Cadastro do cliente no sistema |
| Certificado digital A1/A3 | Verificar validade em `Admin > Configurações Fiscais > Certificado` |

---

## Soluções por tipo de erro

### Boleto sem código de barras válido

1. Verifique se o certificado de integração com o banco está válido (comum expirar sem aviso)
2. Teste a conexão com o gateway: `Admin > Integrações > Testar Conexão`
3. Se a integração estiver OK, verifique os dados do cedente (agência, conta, convênio)
4. Regenere o boleto manualmente: `Financeiro > Cobranças > [cobrança] > Regerar Boleto`

### NF-e rejeitada pela SEFAZ

Os códigos de rejeição mais comuns e suas causas:

| Código | Descrição | Ação |
|---|---|---|
| 204 | Duplicidade de NF-e | Verificar se NF já foi emitida com mesmo número |
| 228 | CNPJ do emitente inválido | Confirmar CNPJ nas configurações fiscais |
| 562 | CEP do destinatário inválido | Atualizar cadastro do cliente |
| 999 | Erro interno SEFAZ | Aguardar e tentar novamente em 30 min |

### Nota fiscal com dados incorretos

1. **NF já autorizada**: não é possível corrigir — emitir **Carta de Correção Eletrônica (CC-e)** para campos não críticos, ou cancelar e reemitir (prazo: até 24h após autorização)
2. **NF ainda não enviada à SEFAZ**: editar os dados diretamente no sistema antes do envio

> ⚠️ Cancelamentos de NF-e após 24h requerem inutilização de numeração. Acionar o time fiscal/contábil antes de qualquer ação.

### Boleto não entregue por e-mail

1. Verificar se o e-mail do cliente está correto no cadastro
2. Checar fila de e-mails no painel: `Admin > E-mails > Fila de Envio`
3. Se o e-mail constou como enviado mas não recebido, solicitar que o cliente verifique spam
4. Reenviar manualmente: `Financeiro > Cobranças > [cobrança] > Reenviar Boleto`

---

## Escalação

Escale para o time financeiro/fiscal se:

- Certificado digital estiver vencido (prazo de renovação: até 3 dias úteis)
- Erro de SEFAZ persistir por mais de 2 horas
- Cliente com NF incorreta e prazo de cancelamento já expirado
- Mais de 10 boletos afetados simultaneamente (provável problema de integração sistêmica)

---

## Tickets relacionados

- TKT-0056, TKT-0234, TKT-0780, TKT-1456, TKT-2033, TKT-3211

---

## Histórico de revisões

| Data | Alteração | Autor |
|---|---|---|
| 2025-01-18 | Criação do artigo | Roberto Alves |
| 2025-06-12 | Adicionada tabela de códigos de rejeição SEFAZ | Patrícia Nunes |
| 2025-12-03 | Inclusão do procedimento de CC-e | Roberto Alves |
| 2026-04-05 | Atualização dos caminhos de log após migração | Diego Ferreira |
