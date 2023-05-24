# Pagerduty 2 Zabbix

https://github.com/sonic-com/pagerduty2zabbix

## What does it do?

It does what's commonly called "2-way ack". That is, it takes WebHooks from
PagerDuty and updates Zabbix, so that the view in Zabbix shows event changes
from PagerDuty.

- PagerDuty incident "acknowledged" will Acknowledge the Zabbix Event and add a comment of who acknowledged it.
- PagerDuty incident "unacknowledged" will Unacknowledge the Zabbix Event and add a comment of who unacknowledged it.
- PagerDuty incident "annotated" (Add Note) will add a note to the Zabbix Event "signed by" the person who made the note.
- PagerDuty incident "priority_updated" will change the priority of the Zabbix event to match (with note of who changed it).
- If triggeredupdate=1, PagerDuty incident "triggered" (created) will add the PD URL as a comment on the Zabbix event.
- If resolvedupdate=1, PagerDuty incident "resolved" will try to close the Zabbix event. (can't close everything).

If there's interest, could update Zabbix for "delegated", "escalated",
"reassigned", "reopened", "responder.added", "responder.replied" and
"status_update_published".  I'm not sure how to even cause some of those,
and the others didn't seem important to have show up in Zabbix.

### TODO

- Verify auth on incoming webhook (token? webhook signature?)

## Installation

1. Install a web server.
2. Configure web server to be able to run CGIs.
3. Either `git clone` this yum repo into someplace you can run CGIs from 
   _or_ copy pd2zabbix.cgi to someplace you can run CGIs from.
   ```bash
   git clone https://github.com/sonic-com/pagerduty2zabbix.git
   ```
4. Install perl and the modules needed by pd2zabbix.cgi:
   On RHEL/CentOS/Rocky/Alma/Fedora, this probably looks like:
   ```bash
   yum install --skip-broken perl perl-CGI perl-JSON \
       perl-libwww-perl perl-LWP-Protocol-https perl-AppConfig 
   ```

   On Debian/Ubuntu, something like:
   ```bash
   apt-get install perl libcgi-pm-perl libjson-perl libwww-perl \
           liblwp-protocol-https-perl libappconfig-perl
   ```

   If you don't have packages available:
   ```bash
   cd pagerduty2zabbix
   cpanm --installdeps .
   ```
5. Configure Zabbix to send alerts to PagerDuty
Copy pagerduty2zabbix.conf.example to ./pagerduty2zabbix.conf or /etc/pagerduty2zabbix.conf
6. 


## References

- <https://developer.pagerduty.com/docs/db0fa8c8984fc-overview>
- <https://www.zabbix.com/documentation/current/en/manual/api>

# Copyright & License

This software is copyright (c) 2023, Sonic.net LLC, and Eric Eisenhart.  All rights reserved.

This is free software; you can redistribute it and/or modify it under
the same terms as the Perl 5 programming language system itself. 
 
 a) the GNU General Public License as published by the Free
    Software Foundation; either version 1, or (at your option) any
       later version, or
 b) the "Artistic License"
