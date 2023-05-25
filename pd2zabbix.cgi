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

    # action bitmap values:
    ZABBIX_CLOSE             => 1,
    ZABBIX_ACK               => 2,
    ZABBIX_ADD_MSG           => 4,
    ZABBIX_CHANGE_SEVERITY   => 8,
    ZABBIX_UNACK             => 16,
    ZABBIX_SUPPRESS          => 32,
    ZABBIX_UNSUPPRESS        => 64,
    ZABBIX_CHANGE_TO_CAUSE   => 128,
    ZABBIX_CHANGE_TO_SYMPTOP => 256,

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
        DEFAULT  => 1,
        ARGCOUNT => ARGCOUNT_ONE,
    },
    pdtoken     => { ARGCOUNT => ARGCOUNT_ONE },
    pdauthtoken => { ARGCOUNT => ARGCOUNT_ONE },
    zabbixtoken => { ARGCOUNT => ARGCOUNT_ONE },
    zabbixurl   => {
        DEFAULT  => 'https://zabbix/zabbix',
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

our $cgi = CGI->new();

if ( $config->get('superearlysuccess') ) {
    print $cgi->header( -status => '202 Accepted Early' );
    warn("Returning success header early.") if $DEBUG;
}

our $ua = LWP::UserAgent->new( agent => 'pagerduty2zabbix (https://github.com/sonic-com/pagerduty2zabbix)' );

if ( $DEBUG >= 5 ) {
    warn "Headers:\n";

    for my $header ( $cgi->http() ) {
        warn "$header: " . $cgi->http($header) . "\n";
    }
}

if ( $DEBUG >= 4 ) {
    warn "POSTDATA:\n";
    warn $cgi->param('POSTDATA') . "\n";
}

# Authenticate (verify token received matches configured token)
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

# Read and parse the incoming PagerDuty webhook payload
my $json_payload = $cgi->param('POSTDATA');
unless ($json_payload) {
    die "No json_payload from webhook POSTDATA\n";
}

my $payload = decode_json($json_payload);
unless ($payload) {
    die "Unable to parse json_payload into payload\n";
}

# Handle the PagerDuty webhook
handle_pagerduty_webhook($payload);

# Send a response back to PagerDuty
print $cgi->header( -status => '202 Accepted Complete Success' );

# PagerDuty webhook handler
sub handle_pagerduty_webhook {
    my ($payload) = @_;

    my $event = $payload->{'event'};
    warn( "parsed event: " . to_json($event) . "\n" ) if $DEBUG >= 2;

    my $event_type = $event->{'event_type'};
    warn("event_type: $event_type\n") if $DEBUG;

    if ( $event_type eq 'pagey.ping' ) {
        warn("pagey.pong\n");
        warn( "event: " . to_json($event) );
        return 1;
    }

    my $self_url = ( $event->{'data'}{'self'} || $event->{'data'}{'incident'}{'self'} );
    warn("self_url: $self_url\n") if $DEBUG >= 2;
    my $html_url = ( $event->{'data'}{'html_url'} || $event->{'data'}{'incident'}{'html_url'} );
    warn("html_url: $html_url\n") if $DEBUG >= 2;

    my $event_details   = get_event_details($self_url);
    my $zabbix_event_id = get_zabbix_event_id($event_details);

    unless ($zabbix_event_id) {
        print $cgi->header( -status => "429 Can't determine zabbix event id; retry" );
        die "Unable to determine zabbix event id";
    }

    # Do appropriate actions on incident event types:
    if ( $event_type eq 'incident.triggered' && $config->get('triggeredupdate') ) {

        # Add PD incident URL as comment on Zabbix event:
        annotate_zabbix_event( $zabbix_event_id, $html_url );
    }
    elsif ( $event_type eq 'incident.acknowledged' ) {

        # Update Zabbix event acknowledgement
        acknowledge_zabbix_event( $zabbix_event_id, $event, $event_details );
    }
    elsif ( $event_type eq 'incident.unacknowledged' ) {

        # Clear acknowledgement from zabbix event
        unacknowledge_zabbix_event( $zabbix_event_id, $event, $event_details );
    }
    elsif ( $event_type eq 'incident.annotated' ) {

        # Add comment to zabbix event when PD event gets a note
        my $who     = $event->{'agent'}{'summary'};
        my $content = $event->{'data'}{'content'};
        $who ||= "PD";
        my $message = "$content -$who";

        annotate_zabbix_event( $zabbix_event_id, $message );
    }
    elsif ( $event_type eq 'incident.resolved' && $config->get('resolvedupdate') ) {

        # Send event close attempt to Zabbix
        close_zabbix_event( $zabbix_event_id, $event, $event_details );
    }
    elsif ( $event_type eq 'incident.priority_updated' ) {

        # Update Zabbix event severity if PD incident priority changed
        update_priority_zabbix_event( $zabbix_event_id, $event, $event_details );
    }

    # PD event types we may want to handle:
    #    "incident.delegated",
    #    "incident.escalated",
    #    "incident.reassigned",
    #    "incident.reopened",
    #    "incident.responder.added",
    #    "incident.responder.replied",
    #    "incident.status_update_published",
}

sub get_event_details {
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
sub get_zabbix_event_id {
    my ($event_details) = @_;
    return $event_details->{'body'}{'details'}{'dedup_key'};
}

# Update Zabbix notes/annotations
sub annotate_zabbix_event {
    my ( $zabbix_event_id, $message ) = @_;
    warn("Annotating Zabbix event $zabbix_event_id with message: $message\n") if $DEBUG;

    my %params = (
        eventids => $zabbix_event_id,
        action   => ZABBIX_ADD_MSG,     # bit-math
        message  => $message
    );
    warn( "update_zabbix_event params: " . to_json( \%params ) ) if $DEBUG >= 2;
    update_zabbix_event(%params);
}

# Update Zabbix event w/acknowledgement
sub acknowledge_zabbix_event {
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
    warn( "update_zabbix_event params: " . to_json( \%params ) ) if $DEBUG >= 2;
    update_zabbix_event(%params);

}

# Update Zabbix event w/unacknowledgement
sub unacknowledge_zabbix_event {
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
    warn( "update_zabbix_event params: " . to_json( \%params ) ) if $DEBUG >= 2;
    update_zabbix_event(%params);

    # TODO:
    # Implement your logic here to update the acknowledgement status of the Zabbix event
    # You need to make API calls to Zabbix to update the event
}

# Update zabbix even with close/resolve.
# Note: can only close some events and silently ignores when it can't.
sub close_zabbix_event {
    my ( $zabbix_event_id, $event, $event_details ) = @_;
    my $who     = $event->{'agent'}{'summary'};
    my $message = "Resolved in PD";
    if ( defined $who ) {
        $message .= " by $who";
    }

    warn("Resolving Zabbix event $zabbix_event_id\n") if $DEBUG;

    my %params = (
        eventids => $zabbix_event_id,
        action   => ZABBIX_CLOSE ^ ZABBIX_ADD_MSG,    # bit-math
        message  => $message
    );
    warn( "update_zabbix_event params: " . to_json( \%params ) ) if $DEBUG >= 2;
    update_zabbix_event(%params);

    # TODO:
    # Implement your logic here to update the acknowledgement status of the Zabbix event
    # You need to make API calls to Zabbix to update the event
}

# Update zabbix event priority
sub update_priority_zabbix_event {
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
    warn( "update_zabbix_event params: " . to_json( \%params ) ) if $DEBUG >= 2;
    update_zabbix_event(%params);

    # TODO:
    # Implement your logic here to update the acknowledgement status of the Zabbix event
    # You need to make API calls to Zabbix to update the event
}

# Update Zabbix event:
sub update_zabbix_event {
    my %params = @_;

    warn("Updating zabbix event\n") if $DEBUG >= 2;

    # https://www.zabbix.com/documentation/current/en/manual/api
    # https://www.zabbix.com/documentation/current/en/manual/api/reference/event/acknowledge
    # curl --request POST \
    #   --url 'https://example.com/zabbix/api_jsonrpc.php' \
    #   --header 'Content-Type: application/json-rpc' \
    #   --header 'Authorization: Bearer 0424bd59b807674191e7d77572075f33' \
    #   --data '{"jsonrpc":"2.0","method":"apiinfo.version","params":{},"id":1}'

    my $zabbixtoken   = $config->get('zabbixtoken');
    my $zabbixbaseurl = $config->get('zabbixurl');
    my $zabbixapiurl  = "$zabbixbaseurl/api_jsonrpc.php";

    my %payload = (
        jsonrpc => '2.0',
        method  => 'event.acknowledge',
        params  => \%params,
        id      => 1,
    );

    my $json = encode_json( \%payload );

    warn("Zabbix API payload: $json\n") if $DEBUG >= 2;

    my $zabbixresponse;
    my $zabbixretries = 0;
    until ( $zabbixresponse && $zabbixresponse->is_success ) {
        $zabbixresponse = $ua->post(
            $zabbixapiurl,
            'Content-Type'  => 'application/json-rpc',
            'Authorization' => "Bearer $zabbixtoken",
            Content         => $json,
        );
        warn( to_json( $zabbixresponse, { allow_blessed => 1 } ) ) if $DEBUG;

        if ( $zabbixretries >= 10 ) {
            warn to_json( $zabbixresponse, { allow_blessed => 1 } );
            die "Couldn't talk to zabbix API after $zabbixretries attempts.\n";
        }
        else {
            $zabbixretries++;
            sleep($zabbixretries);
        }
    }

    warn( to_json( $zabbixresponse, { allow_blessed => 1 } ) ) if $DEBUG >= 4;
}
