#!/usr/bin/perl
# This software is copyright (c) 2023, Sonic.net LLC, and Eric Eisenhart.
# All rights reserved.
# This is free software; you can redistribute it and/or modify it under
# the same terms as the Perl 5 programming language system itself.
#
#  a) the GNU General Public License as published by the Free
#     Software Foundation; either version 1, or (at your option) any
#        later version, or
#  b) the "Artistic License"

use warnings;
use strict;
use CGI;
use JSON;
use LWP::UserAgent;
use CGI::Carp qw(fatalsToBrowser);
use AppConfig qw/:expand :argcount/;

# https://www.zabbix.com/documentation/current/en/manual/api/reference/event/acknowledge#parameters
use constant {

    # Zabbix event action bitmap values:
    ZABBIX_CLOSE             => 1,
    ZABBIX_ACK               => 2,
    ZABBIX_ADD_MSG           => 4,
    ZABBIX_CHANGE_SEVERITY   => 8,
    ZABBIX_UNACK             => 16,
    ZABBIX_SUPPRESS          => 32,
    ZABBIX_UNSUPPRESS        => 64,
    ZABBIX_CHANGE_TO_CAUSE   => 128,
    ZABBIX_CHANGE_TO_SYMPTOP => 256,

    # Zabbix event severities
    ZABBIX_SEV_NOTCLASSIFIED => 0,
    ZABBIX_SEV_INFORMATION   => 1,
    ZABBIX_SEV_WARNING       => 2,
    ZABBIX_SEV_AVERAGE       => 3,
    ZABBIX_SEV_HIGH          => 4,
    ZABBIX_SEV_DISASTER      => 5,
};

our $DEBUG = 0;

# Define the configuration file search paths
my @config_paths = qw(
    .pagerduty2zabbix.conf
    ./pagerduty2zabbix.conf
    /etc/pagerduty2zabbix/pagerduty2zabbix.conf
    /etc/pagerduty2zabbix.conf
);

# Create a new AppConfig object
our $config = AppConfig->new(
    debug => {
        DEFAULT  => 1,              # Default to some debugging if no config file found/parsed
        ARGCOUNT => ARGCOUNT_ONE,
    },
    pdtoken     => { ARGCOUNT => ARGCOUNT_ONE },
    pdauthtoken => { ARGCOUNT => ARGCOUNT_ONE },
    zabbixtoken => { ARGCOUNT => ARGCOUNT_ONE },
    zabbixurl   => {
        DEFAULT  => 'https://zabbix/zabbix',
        ARGCOUNT => ARGCOUNT_LIST,
    },
    zabbixretries => {
        DEFAULT  => 1,
        ARGCOUNT => ARGCOUNT_ONE,
    },
    triggeredupdate => {
        DEFAULT  => 1,
        ARGCOUNT => ARGCOUNT_ONE,
    },
    resolvedupdate => {
        DEFAULT  => 1,
        ARGCOUNT => ARGCOUNT_ONE,
    },
    superearlysuccess => {
        DEFAULT  => 0,
        ARGCOUNT => ARGCOUNT_ONE,
    },
);

# Search for and load the first available configuration file
my $found_config     = 0;
my $config_path_used = '';
foreach my $config_path (@config_paths) {
    if ( -e $config_path ) {
        $config_path_used = $config_path;

        $config->file($config_path);
        $found_config = 1;
        last;
    }
}

# Pull DEBUG value out for ease of use and some debug output...
if ($found_config) {
    $DEBUG = $config->get('debug');
    warn("Config used: $config_path_used\n") if $DEBUG;
    my %vars = $config->varlist('.');
    warn( "Config: " . to_json( \%vars ) . "\n" ) if $DEBUG >= 3;
}
else {
    warn("No config found\n");
    $DEBUG = 1;
}

warn("SECURITY WARNING: Logs may get sensitive data (auth tokens) with debug>=3\n") if $DEBUG >= 3;

# CGI object for later use.
our $cgi = CGI->new();

# If superearlysuccess is set, respond to PagerDuty with success regardless
# of whether or not we succeed.
if ( $config->get('superearlysuccess') ) {
    print $cgi->header( -status => '202 Accepted Early' );
    print "\n";
    warn("Returning success header early.") if $DEBUG;
}

# HTTP/S useragent for talking to pagerduty and zabbix
our $ua = LWP::UserAgent->new( agent => 'pagerduty2zabbix (https://github.com/sonic-com/pagerduty2zabbix)' );

# Annoyingly verbose, but handy for debugging some details
if ( $DEBUG >= 5 ) {
    warn "Headers:\n";

    for my $header ( $cgi->http() ) {
        warn "$header: " . $cgi->http($header) . "\n";
    }
}

# Output the full WebHook payload:
if ( $DEBUG >= 4 ) {
    warn "POSTDATA:\n";
    warn $cgi->param('POSTDATA') . "\n";
}

# Verify auth tokens are there
pagerduty_validate_authentication( $config, $cgi );

# Read and parse the incoming PagerDuty webhook payload
# Exit with error if no payload
my $json_payload = $cgi->param('POSTDATA');
unless ($json_payload) {
    die "No json_payload from webhook POSTDATA\n";
}

# Parse the WebHook JSON into a data structure (nested hash)
my $payload = decode_json($json_payload);
unless ($payload) {
    die "Unable to parse json_payload into payload\n";
}

# Handle the PagerDuty webhook (this is where the magic happens)
pagerduty_handle_webhook($payload);

# Send a success response back to PagerDuty
print $cgi->header( -status => '202 Accepted Complete Success' );

### END MAIN BODY ###
# subroutines after this

# Authenticate WebHook (verify token received matches configured token) if
# we have a token to compare to exits with an error if auth fails.
# "superearlysuccess" param makes the error just a log, not returned to PD,
# otherwise PD will see this as an error.
sub pagerduty_validate_authentication {
    my ( $config, $cgi ) = @_;

    if ( $config->get('pdauthtoken') ) {
        my $pdauthtoken  = $config->get('pdauthtoken');
        my $pdauthheader = $cgi->http('Authentication');
        warn("Auth header: $pdauthheader\n")      if $DEBUG >= 3;
        warn("Auth token config: $pdauthtoken\n") if $DEBUG >= 3;
        if ( defined($pdauthheader) && $pdauthtoken eq $pdauthheader ) {
            warn("Auth token verified\n") if $DEBUG;
        }
        else {
            print $cgi->header( -status => '401 Invalid Authentication Header' );
            die("Auth header didn't match configured auth token\n");
        }
    }
    else {
        warn("No stored auth token to verify.\n") if $DEBUG;
    }

}

# WebHook->event->incident->alert(s)

# PD sends WebHook with an outbound "event", containing:
#   - type of update (event_type)
#   - possible additional event data (comment contents)
#   - Some incident data (inc self url)
# Incident contains 1 or more "alerts" that can be fetched.
# Alerts are what Zabbix had sent and have the zabbix event id needed to
# update zabbix.

# PagerDuty webhook handler -- most of the work happens here
sub pagerduty_handle_webhook {
    my ($payload) = @_;

    # pull the "event" (main data) out of the WebHook payload
    my $event = $payload->{'event'};
    warn( "parsed event: " . to_json($event) . "\n" ) if $DEBUG >= 2;

    # Work out what type of event it is
    my $event_type = $event->{'event_type'};
    warn("event_type: $event_type\n") if $DEBUG;

    # Special case: if you're doing a test (ping), there will be no useful
    # info, so output something to log and return to success
    if ( $event_type eq 'pagey.ping' ) {
        warn("pagey.pong\n");
        warn( "event: " . to_json($event) );
        return 1;
    }

    # Get the PD event API endpoint for this event
    my $self_url = ( $event->{'data'}{'self'} || $event->{'data'}{'incident'}{'self'} );
    warn("self_url: $self_url\n") if $DEBUG >= 2;

    # Get human-usable PD event URL
    my $html_url = ( $event->{'data'}{'html_url'} || $event->{'data'}{'incident'}{'html_url'} );
    warn("html_url: $html_url\n") if $DEBUG >= 2;

    # Fetch more details from PagerDuty
    my $event_details = pagerduty_get_incident_details($self_url);

    # Those more details from PD should include info to work out the zabbix
    # event id for use with the Zabbix API
    my $zabbix_event_id = zabbix_get_event_id($event_details);

    # If we couldn't work out a zabbix event id, we can't update zabbix.
    # In case this was due to transient PagerDuty API issues, return "429"
    # to tell PD to try the webhook again a bit later.
    # Check PD WebHook docs for retry limits.
    unless ($zabbix_event_id) {
        print $cgi->header( -status => "429 Can't determine zabbix event id; retry" );
        die "Unable to determine zabbix event id";
    }

    # Do appropriate actions on incident event types

    # triggered==created (or maybe also end of silencing)
    if ( $event_type eq 'incident.triggered' && $config->get('triggeredupdate') ) {

        # Add PD incident URL as comment on Zabbix event:
        zabbix_event_annotate( $zabbix_event_id, $html_url );
    }

    # The original main reason for this: PD ACK to Zabbix ACK
    elsif ( $event_type eq 'incident.acknowledged' ) {

        # Update Zabbix event acknowledgement
        zabbix_event_acknowledge( $zabbix_event_id, $event, $event_details );
    }

    # And UNACK
    elsif ( $event_type eq 'incident.unacknowledged' ) {

        # Clear acknowledgement from zabbix event
        zabbix_event_unacknowledge( $zabbix_event_id, $event, $event_details );
    }

    # If a note is added in PD (if note added when doing another action,
    # sends webhook for both that action and the note)
    elsif ( $event_type eq 'incident.annotated' ) {

        # Add comment to zabbix event when PD event gets a note
        my $who     = $event->{'agent'}{'summary'};
        my $content = $event->{'data'}{'content'};
        $who ||= "PD";
        my $message = "$content -$who";

        zabbix_event_annotate( $zabbix_event_id, $message );
    }

    # If someone clicks "resolve" in PD, try to close the Zabbix event
    elsif ( $event_type eq 'incident.resolved' && $config->get('resolvedupdate') ) {

        # Send event close attempt to Zabbix
        zabbix_event_close( $zabbix_event_id, $event, $event_details );
    }

    # If priority changed in PD, update zabbix event severity to match
    # TODO: make this configurable?
    elsif ( $event_type eq 'incident.priority_updated' ) {

        # Update Zabbix event severity if PD incident priority changed
        zabbix_event_update_priority( $zabbix_event_id, $event, $event_details );
    }

    # If don't know what to do, log it.  Not an error, since could have
    # simply accepted the default of WebHook sending all event types.
    else {
        warn("Don't know how to handle event type $event_type\n");
    }

    # Other PD event types that we don't currently do anything with:
    #    "incident.delegated",
    #    "incident.escalated",
    #    "incident.reassigned",
    #    "incident.reopened",
    #    "incident.responder.added",
    #    "incident.responder.replied",
    #    "incident.status_update_published",
}

# Use PD event API to get additional details on the incident.
# Needed for fetching info that includes the zabbix event ID for the zabbix API.
sub pagerduty_get_incident_details {
    my ($self_url) = @_;
    my $pdtoken = $config->get('pdtoken');

    my $pd_response = $ua->get( "${self_url}?include[]=body", 'Authorization' => "Token token=${pdtoken}", );
    warn( to_json( $pd_response, { allow_blessed => 1 } ) ) if $DEBUG >= 4;
    if ( $pd_response->is_success ) {
        my $pd_json_content = $pd_response->content();
        my $content         = decode_json($pd_json_content);
        return $content->{'incident'};
    }
    else {
        die "Unable to fetch details from PagerDuty\n";
    }

}

# Get the Zabbix event ID associated with a PagerDuty incident
# TODO: explore backup options in case dedup_key not there... zabbix URL has it, for instance.
sub zabbix_get_event_id {
    my ($event_details) = @_;
    my $eventid = '';

    # Primary place we find the eventid:
    $eventid = $event_details->{'body'}{'details'}{'dedup_key'};

    # Second place to look for eventid:
    unless ($eventid) {
        $eventid = $event_details->{'body'}{'details'}{'__pd_cef_payload'}{'dedup_key'};
    }

    # If don't find event id on its own, try parsing out of the URL to the zabbix event
    unless ($eventid) {
        my $zabbixurl = $event_details->{'body'}{'details'}{'links'}[0]{'href'};
        $zabbixurl ||= $event_details->{'body'}{'details'}{'contexts'}[0]{'href'};
        if ( $zabbixurl =~ m/[?&]eventid=(\d+)/ ) {
            $eventid = $1;
        }
    }
    return $eventid;
}

# Add a message to the zabbix event.
sub zabbix_event_annotate {
    my ( $zabbix_event_id, $message ) = @_;
    warn("Annotating Zabbix event $zabbix_event_id with message: $message\n") if $DEBUG;

    my %params = (
        eventids => $zabbix_event_id,
        action   => ZABBIX_ADD_MSG,     # bit-math
        message  => $message
    );
    warn( "zabbix_event_update params: " . to_json( \%params ) ) if $DEBUG >= 2;
    zabbix_event_update(%params);
}

# Update Zabbix event w/acknowledgement.
# Includes a "ACK'd in PD by $person" note.
sub zabbix_event_acknowledge {
    my ( $zabbix_event_id, $event, $event_details ) = @_;
    my $who     = $event->{'agent'}{'summary'};
    my $message = "ACK'd in PD";
    if ( defined $who ) {
        $message .= " by $who";
    }
    warn("Acknowledging Zabbix event $zabbix_event_id\n") if $DEBUG;

    my %params = (
        eventids => $zabbix_event_id,
        action   => ZABBIX_ACK ^ ZABBIX_ADD_MSG,    # bit-math
        message  => $message
    );
    warn( "zabbix_event_update params: " . to_json( \%params ) ) if $DEBUG >= 2;
    zabbix_event_update(%params);

}

# Update Zabbix event w/unacknowledgement.
# Includes an "un-ACK'd in PD by $person" note.
sub zabbix_event_unacknowledge {
    my ( $zabbix_event_id, $event, $event_details ) = @_;
    my $who     = $event->{'agent'}{'summary'};
    my $message = "un-ACK'd in PD";
    if ( defined $who ) {
        $message .= " by $who";
    }
    warn("Unacknowledging Zabbix event $zabbix_event_id\n") if $DEBUG;

    my %params = (
        eventids => $zabbix_event_id,
        action   => ZABBIX_UNACK ^ ZABBIX_ADD_MSG,    # bit-math
        message  => $message
    );
    warn( "zabbix_event_update params: " . to_json( \%params ) ) if $DEBUG >= 2;
    zabbix_event_update(%params);

    # TODO:
    # Implement your logic here to update the acknowledgement status of the Zabbix event
    # You need to make API calls to Zabbix to update the event
}

# Update zabbix even with close/resolve.
# Adds a "Resolved in PD by $person" note.
# Note: can only close some events and silently ignores when it can't.
sub zabbix_event_close {
    my ( $zabbix_event_id, $event, $event_details ) = @_;
    my $who = $event->{'agent'}{'summary'};

    my $message = "Resolved in PD";
    if ( defined $who ) {
        $message .= " by $who";
    }

    warn("Acking Zabbix event $zabbix_event_id before close attempt\n") if $DEBUG;

    my %ack_params = (
        eventids => $zabbix_event_id,
        action   => ZABBIX_ACK ^ ZABBIX_ADD_MSG,    # bit-math
        message  => $message
    );

    warn( "zabbix_event_update ack_params: " . to_json( \%ack_params ) ) if $DEBUG >= 2;
    zabbix_event_update(%ack_params);

    warn("Resolving Zabbix event $zabbix_event_id\n") if $DEBUG;

    my %close_params = (
        eventids => $zabbix_event_id,
        action   => ZABBIX_CLOSE,                   # bit-math
    );
    warn( "zabbix_event_update close_params: " . to_json( \%close_params ) ) if $DEBUG >= 2;
    zabbix_event_update(%close_params);

    # TODO:
    # Implement your logic here to update the acknowledgement status of the Zabbix event
    # You need to make API calls to Zabbix to update the event
}

# Update zabbix event priority
# TODO: make this configurable?
sub zabbix_event_update_priority {
    my ( $zabbix_event_id, $event, $event_details ) = @_;
    my $who        = $event->{'agent'}{'summary'};
    my %priorities = (
        P5 => ZABBIX_SEV_INFORMATION,
        P4 => ZABBIX_SEV_WARNING,
        P3 => ZABBIX_SEV_AVERAGE,
        P2 => ZABBIX_SEV_HIGH,
        P1 => ZABBIX_SEV_DISASTER,
    );
    my $pd_priority     = $event->{'data'}{'priority'}{'summary'};
    my $zabbix_severity = $priorities{$pd_priority} || ZABBIX_SEV_NOTCLASSIFIED;
    my $message         = "PD Priority changed to $pd_priority";
    if ( defined $who ) {
        $message .= " by $who";
    }

    warn("Updating Zabbix event priority $zabbix_event_id to $pd_priority/$zabbix_severity\n") if $DEBUG;

    my %params = (
        eventids => $zabbix_event_id,
        action   => ZABBIX_CHANGE_SEVERITY ^ ZABBIX_ADD_MSG,    # bit-math
        message  => $message,
        severity => $zabbix_severity,
    );
    warn( "zabbix_event_update params: " . to_json( \%params ) ) if $DEBUG >= 2;
    zabbix_event_update(%params);

    # TODO:
    # Implement your logic here to update the acknowledgement status of the Zabbix event
    # You need to make API calls to Zabbix to update the event
}

# Update Zabbix event.
# This is what everything else calls to update Zabbix via the Zabbix API.
# Arguments are hash-style arguments of what to update, including the mysterious bit-math-based actions.
# Makes multiple attempts, in case a clustered config has something down. With slight backoff.
# TODO: make retry stuff configurable.
sub zabbix_event_update {
    my %params = @_;

    warn("Updating zabbix event\n") if $DEBUG >= 2;

    # https://www.zabbix.com/documentation/current/en/manual/api
    # https://www.zabbix.com/documentation/current/en/manual/api/reference/event/acknowledge
    # curl --request POST \
    #   --url 'https://example.com/zabbix/api_jsonrpc.php' \
    #   --header 'Content-Type: application/json-rpc' \
    #   --header 'Authorization: Bearer 3159081342135409871513098' \
    #   --data '{"jsonrpc":"2.0","method":"apiinfo.version","params":{},"id":1}'

    my $maxretries     = $config->get('zabbixretries');
    my $zabbixtoken    = $config->get('zabbixtoken');
    my $zabbixbaseurls = $config->get('zabbixurl');

    my %payload = (
        jsonrpc => '2.0',
        method  => 'event.acknowledge',
        params  => \%params,
        id      => 1,
    );

    my $json = encode_json( \%payload );

    warn("Zabbix API payload: $json\n") if $DEBUG >= 2;

    my $zabbixresponse;
OUTER: for my $zabbixbaseurl (@$zabbixbaseurls) {
        my $zabbixretries = 0;
        my $zabbixapiurl  = "$zabbixbaseurl/api_jsonrpc.php";

        warn("Zabbix URL: $zabbixapiurl\n") if $DEBUG >= 2;

    INNER: until ( $zabbixresponse && $zabbixresponse->is_success ) {
            $zabbixresponse = $ua->post(
                $zabbixapiurl,
                'Content-Type'  => 'application/json-rpc',
                'Authorization' => "Bearer $zabbixtoken",
                Content         => $json,
            );

            if ( $zabbixresponse && $zabbixresponse->is_success ) {
                warn("Zabbix API update successful on try $zabbixretries\n") if $DEBUG;
                warn( "Response from Zabbix: " . to_json( $zabbixresponse, { allow_blessed => 1 } ) ) if $DEBUG >= 2;
                last OUTER;
            }
            else {
                warn("Zabbix API attempt $zabbixretries\n")
                    if ( $DEBUG >= 2 or ( $DEBUG >= 1 and $zabbixretries >= 3 ) );
                warn( "Response from Zabbix: " . to_json( $zabbixresponse, { allow_blessed => 1 } ) ) if $DEBUG >= 2;

                if ( $zabbixretries >= $maxretries ) {
                    warn to_json( $zabbixresponse, { allow_blessed => 1 } );
                    warn "Couldn't talk to zabbix API after $zabbixretries attempts.\n";
                    next OUTER;
                }
                else {
                    $zabbixretries++;
                    warn("Waiting $zabbixretries seconds before trying Zabbix API again\n") if $DEBUG >= 2;
                    sleep($zabbixretries);
                }
            }
        }
    }

    warn( to_json( $zabbixresponse, { allow_blessed => 1 } ) ) if $DEBUG >= 4;
}
