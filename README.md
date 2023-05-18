# Pagerduty 2 Zabbix

## 2-way ack

A simple CGI that accepts WebHooks from PagerDuty and updates the related Zabbix events.

### DONE

-

### TODO

- Run CGI
- Config
  - Find somewhere in /etc and include current dir somehow in what's used
    (so dev and prod can have same code but diff configs)
  - incoming webhook auth token or webhook signature info (from PD)
  - outgoing zabbix auth info
  - outgoing zabbix url/etc
- Accept incoming webhook
- Return `202 Accepted`
- Verify auth on incoming webhook (token? webhook signature?)
- Parse PD incident.acknowledged incoming event
  - Send Zabbix event.acknowledge for acknowledged incident
    - action: acknowledge event (acknowledge&add-message?)
    - message: who acknowledged
- Parse PD incident.unacknowledged event
  - Send Zabbix event.acknowlege for unacknowledged incident
    - action: unackknowledge (unacknowledge&add-message?)
    - message: who acknowledged
- Parse PD incident.triggered
  - Send zabbix event.acknowledge
    - action: add message
    - message: link to PD incident?

## References

- <https://developer.pagerduty.com/docs/db0fa8c8984fc-overview>
- <https://www.zabbix.com/documentation/current/en/manual/api>

### Zabbix event actions

- 1 - close problem;
- 2 - acknowledge event;
- 4 - add message;
- 8 - change severity;
- 16 - unacknowledge event;
- 32 - suppress event;
- 64 - unsuppress event;
- 128 - change event rank to cause;
- 256 - change event rank to symptom.

### PagerDuty incident event types

- incident.acknowledged
- incident.annotated (note added)
- incident.delegated (reassigned to another escalation policy)
- incident.escalated (escalated within escalation policy)
- indident.priority_updated (priortity changed)
- incident.reassigned (assigned to diff user)
- incident.reopened
- incident.responder.added
- incident.responder.replied
- incident.status_update_published
- incident.triggered (new incident)
- incident.unacknowledged
