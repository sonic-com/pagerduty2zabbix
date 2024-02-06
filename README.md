# Pagerduty 2 Zabbix

![perl compile](https://github.com/sonic-com/pagerduty2zabbix/actions/workflows/perlcompile.yml/badge.svg)
![perltidy](https://github.com/sonic-com/pagerduty2zabbix/actions/workflows/perltidy.yml/badge.svg)
![license: GPLv1+ or Artistic License](https://img.shields.io/badge/license-GPLv1%2B%20or%20Artistic%20License-green)
![release](https://img.shields.io/github/v/release/sonic-com/pagerduty2zabbix?display_name=tag)

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
- PD "resolved" status can mean this is a "child" in an incident merge,
  user marked 'resolved', or resolved because Zabbix closed event via API.
  - For merges, if pdmergeaction=merge the "parent" incident will be
    marked as a "cause", and the child as a "symptom" with parent as
    it's "cause". In Zabbix you'll see the parent in events list and
    can expand to see children.
  - If merge and pdmergeaction=ignore, nothing at all is done.
  - If merge and pdmergeaction=resolve, will do same as not a merge.
  - If not a merge, and resolvedupdate=1, will try to close the
    Zabbix event.  (can't close everything, but tries).
  - Otherwise, will do nothing.

If there's interest, could update Zabbix for "delegated", "escalated",
"reassigned", "reopened", "responder.added", "responder.replied" and
"status_update_published".  I'm not sure how to even cause some of those,
and the others didn't seem important to have show up in Zabbix.

The Priority/severity mappings are configurable, but default to a config
that should work well in a stock PagerDuty setup.

### Requirements
- Zabbix 6.4+ (might work with older, I'm testing on 6.4)
- perl 5.10+
- valid SSL certs on zabbix web (or needs to use http not https)
- Perl modules (in cpanfile and all are commonly available in most distros):
  - CGI
  - JSON
  - LWP::UserAgent
  - LWP::Protocol::https
  - CGI::Carp
  - AppConfig

This CGI is stateless, so can easily be clustered for HA. Probably can run
on same servers as zabbix-web, but we run it elsewhere because our Zabbix
servers are purely internal/VPN-only.

## Installation

1. Install a web server.
2. Configure web server to be able to run CGIs.
3. Open firewall holes so that (at least) PagerDuty's WebHook IPs can hit
   the http or https port that you're using. https://developer.pagerduty.com/docs/9a349b09b87b7-webhook-i-ps
4. If you're using https, make sure you have a valid certificate.
5. Either `git clone` this yum repo into someplace you can run CGIs from
   _or_ copy pd2zabbix.cgi to someplace you can run CGIs from.
   ```bash
   git clone https://github.com/sonic-com/pagerduty2zabbix.git
   ```
   * On a RHEL/Rocky/Alma 9 server, this should work:
    ```bash
    cd /var/www/cgi-bin
    git clone https://github.com/sonic-com/pagerduty2zabbix.git
    ```
6. Install perl and the modules needed by pd2zabbix.cgi:

   On RHEL/CentOS/Rocky/Alma/Fedora, this probably looks like:
   ```bash
   yum install --skip-broken perl perl-CGI perl-JSON \
       perl-JSON-XS perl-Cpanel-JSON-XS \
       perl-libwww-perl perl-LWP-Protocol-https perl-AppConfig
   ```

   On Debian/Ubuntu, something like:
   ```bash
   apt-get install perl libcgi-pm-perl libjson-perl libjson-xs-perl \
           libwww-perl liblwp-protocol-https-perl libappconfig-perl
   ```

   If you don't have packages available:
   ```bash
   cd pagerduty2zabbix
   cpanm --installdeps . # This should read cpanfile
   ```
7. Verify you have appropriate perl modules installed with `perl -c pd2zabbix.cgi`
8. Verify your CGI config is correct with web browser or `curl` on the URL for
   pd2zabbix.cgi. If it's working right, it should give an error that includes:
   ```
   No json_payload from webhook POSTDATA
   ```
9. Configure Zabbix to send alerts to PagerDuty with the Zabbix WebHook included with recent Zabbix versions.

   If you've updated Zabbix, this may need to be updated to a version of
   the script that sets pagerduty "dedup_key" to zabbix "eventid".

   I recommend setting the `token` in the `Media type` to `{ALERT.SENDTO}`
   and putting your PagerDuty API token into "Send to" of the user's media
   configuration. (so you have the easy option of additional PD integrations for different teams, etc)
   If you don't have any plans to have multiple groups or to route Zabbix
   alerts to different PagerDuty integrations/services/automation, don't
   worry about this.
10. Copy pagerduty2zabbix.conf.example to ./pagerduty2zabbix.conf or /etc/pagerduty2zabbix.conf
   Make sure not accessible to public, since needs a secret (zabbix API key).
11. Edit pagerduty2zabbix.conf:
   - Get an API token from PagerDuty that can update the relevant PagerDuty events and set `pdtoken` to that.
     (profile pic > User Settings > Create API User Token)
   - Make a random string and set `pdauthtoken` to that.
   - Get an API token from zabbix that can update the relevant events (I
     used one for same user as for pagerduty alerts), and set `zabbixtoken`
     to that.
   - Set `zabbixurl` to the URL of your zabbix frontpage.
     - Set multiple times if you have multiple frontends you want this to try (exits on first success).
   - If you want multiple retries for each zabbix URL, set `zabbixretries` > 1.
   - If you don't want PD event urls as a comment on new zabbix events, set `triggeredupdate=0`.
   - If you don't want clicking "resolve" in PD to close Zabbix events, set `resolvedupdate=0`.
12. Optional Testing:
   - You should be able to access the URL from a web-browser or with `curl`.
     It will return a "Software error" error about "No json_payload from webhook POSTDATA"
     when tested this way.
   - You should _not_ have to bypass any certificate warnings.
   - If everything is configured appropriately, you should be able to test a
     ping with curl like this (change the authentication token to your pdauthtoken
     value and the URL to the URL of your copy of pd2zabbix.cgi)
     ```
     curl --header 'Authentication: changeme' \
       --json '{"event": {"id": "01CH754SM17TWPE2V2H4VPBRO7","event_type": "pagey.ping","resource_type": "pagey","occurred_at": "2021-12-08T22:58:53.510Z","agent": null,"client": null,"data": {"message": "Hello from your friend Pagey!","type": "ping"}}}'
       https://zabbix.example.com/cgi-bin/pagerduty2zabbix/pd2zabbix.cgi
     ```
13. In PagerDuty, go to the service Zabbix is sending events to, and:
   1. Add a webhook
   2. For webhook URL, your fully-qualified URL for external access
      - If you did a `git clone` into `/var/www/cgi-bin` on
        RHEL/Rocky/Alma/CentOS, then this will probably look like
        `https://zabbix.example.com/cgi-bin/pagerduty2zabbix/pd2zabbix.cgi`
   3. Webhook Status: Active
   4. Event Subscription: incident.acknowledged, incident.annotated,
      incident.priority_updated, incident.resolved, incident.triggered,
      and incident.unacknowledged.
   5. Add custom header:
      - Name: `Authentication`
      - Value: The value from `pdauthtoken` earlier
   6. Save.
   7. Do a "Send Test Event".
      - The access logs should show a POST to the CGI from one of the
        PagerDuty WebHook IPs and a status code of 202, like:
        ```
        54.213.187.133 - - [06/Feb/2024:15:27:14 -0800] "POST /cgi-bin/pagerduty2zabbix/pd2zabbix.cgi HTTP/1.1" 202 87
        ```
      - If you're able to watch error logs (where STDERR of CGIs go), you should see `pagey.pong` in that
        log. Something like:
        ```
        [Tue Feb 06 15:27:14.129996 2024] [cgid:error] [pid 1887:tid 1945] [client 54.213.187.133:53658] [Tue Feb  6 15:27:14 2024] pd2zabbix.cgi: pagey.pong: /var/www/cgi-bin/pagerduty2zabbix/pd2zabbix.cgi
        ```
        Exact formatting depends quite a bit on exact versions of httpd,
        perl, and perl libraries.

## FAQ/Common Problems/Likely Problems:

- "Unable to determine zabbix event id" in error log:
  This means that it couldn't find a `dedup_key` (or `alert_key`) in the PagerDuty event.

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
