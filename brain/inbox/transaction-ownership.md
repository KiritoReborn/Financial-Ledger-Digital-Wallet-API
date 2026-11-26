---
title: Transaction ownership in the API
author: Harshith
date: 2026-11-26
category: inbox
tags: [sqlite, transactions]
requirements: [FR-3.1, SK-1]
source: SRS.pdf, section 2.1
---

# Transaction ownership in the API

The API acquires the write lock before calling the replay and posting services. Both services use the caller's SQLite connection. This lets a failure after posting roll back the balance change and replay record together.

The provider implementation and rollback check are recorded in [[projects/h03-sqlite-provider]].
