# DATABASE.md

## Database Structure

### Tabella `users`
| Campo        | Tipo      | Note                    |
|--------------|-----------|--------------------------|
| id           | INTEGER PK|                          |
| username     | TEXT UNIQ | identificativo locale    |
| telegram_id  | INTEGER   | ID Telegram              |
| created_at   | DATETIME  |                          |
| linked_at    | DATETIME  |                          |

---

### Tabella `login_requests`
| Campo        | Tipo      | Note                                 |
|--------------|-----------|---------------------------------------|
| id           | UUID PK   | identificatore richiesta login        |
| user_id      | INT       | FK users.id                           |
| status       | TEXT      | pending / approved / denied / expired |
| created_at   | DATETIME  |                                       |

---

### Indici raccomandati
- `users(username)`
- `users(telegram_id)`
- `login_requests(user_id)`