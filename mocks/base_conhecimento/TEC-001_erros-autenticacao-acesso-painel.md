---
id: TEC-001
title: "Erros de autenticação e acesso ao painel de controle"
category: técnica
tags: [autenticação, login, painel, erro-500, acesso]
module: autenticação
audience: interno
created_at: 2025-03-10
updated_at: 2026-04-18
author: Mariana Costa
---

# Erros de autenticação e acesso ao painel de controle

## Descrição do problema

Clientes relatam erro ao tentar acessar o painel de controle, geralmente após atualização de sistema ou expiração de sessão. Os sintomas mais comuns incluem:

- Tela de login em loop (redireciona para o login após autenticar)
- Erro 500 ao clicar em qualquer item do menu após login
- Mensagem "Sessão expirada" mesmo com credenciais corretas
- Acesso bloqueado para usuários com perfis específicos (ex: admin, financeiro)

---

## Diagnóstico

### 1. Verificar logs de autenticação

Antes de qualquer ação, solicite ao cliente que reproduza o erro e capture o log. Os logs ficam em:

```
/var/log/app/auth.log
```

Procure por entradas com `ERROR` ou `WARN` no intervalo de tempo relatado.

### 2. Perguntas para o cliente

- O erro ocorre para todos os usuários ou apenas alguns?
- O problema começou após alguma atualização ou mudança de configuração?
- Qual navegador e versão está sendo usado?
- O cliente utiliza SSO (Single Sign-On) ou autenticação própria?

### 3. Checklist rápido

| Verificação | Como checar |
|---|---|
| Token JWT expirado | Inspecionar cookie de sessão no navegador (F12 > Application > Cookies) |
| Cache corrompido | Pedir para limpar cache e cookies e tentar novamente |
| Bloqueio por IP | Verificar no painel de segurança se o IP do cliente está na lista de bloqueio |
| Certificado SSL vencido | Checar validade do certificado do ambiente do cliente |

---

## Solução

### Caso 1 — Loop de login (problema de cookie/sessão)

1. Peça ao cliente para limpar os cookies do navegador para o domínio da aplicação.
2. Tente acessar em uma aba anônima.
3. Se resolver, o problema é de cache local — instrua a limpeza completa.
4. Se não resolver, acesse o painel de administração e **invalide a sessão ativa** do usuário:
   - Menu `Admin > Usuários > [usuário] > Encerrar sessões ativas`

### Caso 2 — Erro 500 após login

1. Verifique se o erro é genérico ou relacionado a um módulo específico.
2. Consulte os logs de aplicação (`/var/log/app/app.log`) pelo stack trace.
3. Erro frequente: **permissão de banco de dados** — verifique se o usuário do serviço tem acesso à tabela `user_sessions`.
4. Se o erro surgiu após update, verifique o changelog da versão e se as migrations foram executadas corretamente.

### Caso 3 — Usuários com perfil específico bloqueados

1. Acesse `Admin > Perfis de Acesso` e verifique se o perfil do usuário está ativo.
2. Confirme se houve alteração recente nas permissões do perfil.
3. Reative o perfil ou restaure as permissões padrão conforme documentação de perfis.

---

## Escalação

Se nenhuma das soluções acima resolver em até **2 horas**, escale para o time de backend com as seguintes informações:

- ID do cliente
- Usuário(s) afetado(s)
- Log de autenticação completo
- Versão da aplicação em uso

> ⚠️ **Atenção:** Tickets com esse problema marcados como prioridade **crítico** devem ser escalados imediatamente, sem aguardar as 2 horas.

---

## Tickets relacionados

- TKT-0082, TKT-0319, TKT-0874, TKT-1203

---

## Histórico de revisões

| Data | Alteração | Autor |
|---|---|---|
| 2025-03-10 | Criação do artigo | Mariana Costa |
| 2025-09-04 | Adicionado Caso 3 (perfis bloqueados) | Felipe Oliveira |
| 2026-04-18 | Atualização do caminho de logs após migração de servidor | Mariana Costa |
