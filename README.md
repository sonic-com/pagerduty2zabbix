# Pagerduty 2 Zabbix

https://github.com/sonic-com/pagerduty2zabbix

## What does it do?

It does what's commonly called "2-way ack". That is, it takes WebHooks from
PagerDuty and updates Zabbix, so that the view in Zabbix shows event changes
from PagerDuty.

- PagerDuty incident "acknowledged" will Acknowledge the Zabbix Event and
  add a comment of who acknowledged it.
- PagerDuty incident "unacknowledged" will Unacknowledge the Zabbix Event 
  and add a comment of who unacknowledged it.
- PagerDuty incident "annotated" (Add Note) will add a note to the Zabbix
  Event "signed by" the person who made the note.
- PagerDuty incident "priority_updated" will change the priority of the
  Zabbix event to match (with note of who changed it).
- If triggeredupdate=1, PagerDuty incident "triggered" (created) will add
  the PD URL as a comment on the Zabbix event.
- If resolvedupdate=1, PagerDuty incident "resolved" will try to close the
  Zabbix event.  (can't close everything).

If there's interest, could update Zabbix for "delegated", "escalated",
"reassigned", "reopened", "responder.added", "responder.replied" and
"status_update_published".  I'm not sure how to even cause some of those,
and the others didn't seem important to have show up in Zabbix.

### TODO

- Verify auth on incoming webhook (token? webhook signature?)

## Installation

### Requirements
- Zabbix 6.4+ (might work with older, I'm testing on 6.4)
- perl 5.10+

This CGI is stateless, so can easily be clustered for HA. Probably can run
on same servers as zabbix-web, but we run it elsewhere because our Zabbix
servers are purely internal/VPN-only.

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
   cpanm --installdeps . # This should read cpanfile
   ```
5. Verify you have appropriate perl modules installed with `perl -c pd2zabbix.cgi`
6. Verify your CGI config is correct with web browser or `curl` on the URL for 
   pd2zabbix.cgi. If it's working right, it should give an error that includes:
   ```
   No json_payload from webhook POSTDATA
   ```
7. Configure Zabbix to send alerts to PagerDuty with the Zabbix WebHook included with recent Zabbix versions.
   
   If you've updated Zabbix, this may need to be updated to a version of
   the script that sets pagerduty "dedup_key" to zabbix "eventid".)

   I recommend setting the `token` in the `Media type` to `{ALERT.SENDTO}`
   and putting your PagerDuty API token into "Send to" of the user's media
   configuration.
6. Copy pagerduty2zabbix.conf.example to ./pagerduty2zabbix.conf or /etc/pagerduty2zabbix.conf
7. Edit pagerduty2zabbix.conf:
   - Get a token from PagerDuty that can update the relevant PagerDuty events and set `pdtoken` to that
   - Make a random string and set `pdauthtoken` to that.
   - Get an API token from zabbix that can update the relevant events (I
     used one for same user as for pagerduty alerts), and set `zabbixtoken`
     to that.
   - Set `zabbixurl` to the URL of your zabbix frontpage
   - If you don't want PD event urls as a comment on new zabbix events, set `triggeredupdate=0`.
   - If you don't want clicking "resolve" in PD to close Zabbix events, set `resolvedupdate=0`.
8. In PagerDuty, go to the service Zabbix is sending events to, and:
   1. Add a webhook
   2. For webhook URL, your URL
   3. Webhook Status: Active
   4. Event Subscription: incident.acknowledged, incident.annotated,
      incident.priority_updated, incident.resolved, incident.triggered,
      and incident.unacknowledged.
   5. Add custom header:
      - Name: `Authentication`
      - Value: The value from `pdauthtoken` earlier
   6. Save.
   7. If you're able to watch error logs (where STDERR of CGIs go), do a "Send Test Event".
      You should see `pagey.pong` in that log.

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
