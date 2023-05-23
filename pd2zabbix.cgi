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
use Data::Dumper;
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
);

# Search for and load the first available configuration file
my $found_config = 0;
foreach my $config_path (@config_paths) {
    if ( -e $config_path ) {
        warn("Reading config $config_path\n");
        $config->file($config_path);
        $found_config = 1;
        last;
    }
}

if ($found_config) {
    $DEBUG = $config->get('debug');
    $DEBUG >= 3 && warn( Dumper($config) );
}
else {
    warn("No config found");
    $DEBUG = 1;
}

our $cgi = CGI->new();

our $ua = LWP::UserAgent->new( agent => 'pagerduty2zabbix (https://github.com/sonic-com/pagerduty2zabbix)' );

# Always tell PD we got the message right away:
#print $cgi->header();

if ($DEBUG) {
    warn "Headers:\n";

    for my $header ( $cgi->http() ) {
        warn "$header: " . $cgi->http($header) . "\n";
    }
    warn "POSTDATA:\n";
    warn Dumper( $cgi->param('POSTDATA') );
}

# Read and parse the incoming PagerDuty webhook payload
my $json_payload = $cgi->param('POSTDATA');
unless ($json_payload) {
    die "No json_payload from webhook POSTDATA";
}

my $payload = decode_json($json_payload);
unless ($payload) {
    die "Unable to parse json_payload into payload";
}

# Handle the PagerDuty webhook
handle_pagerduty_webhook($payload);

# Send a response back to PagerDuty
my $response = { status => 'success' };
print $cgi->header('application/json');
print encode_json($response);

# PagerDuty webhook handler
sub handle_pagerduty_webhook {
    my ($payload) = @_;

    my $event = $payload->{'event'};
    $DEBUG >= 3 && warn( "event: " . Dumper($event) . "\n" );
    my $self_url = ( $event->{'data'}{'self'} || $event->{'data'}{'incident'}{'self'} );
    $DEBUG && warn("self_url: $self_url\n");
    my $html_url = ( $event->{'data'}{'html_url'} || $event->{'data'}{'incident'}{'html_url'} );
    $DEBUG && warn("html_url: $html_url\n");

    my $event_details   = get_event_details($self_url);
    my $zabbix_event_id = get_zabbix_event_id($event_details);

    my $event_type = $event->{'event_type'};
    $DEBUG && warn("event_type: $event_type\n");

    # Do appropriate actions on incident event types:
    if ( $event_type eq 'incident.triggered' ) {
        if ($zabbix_event_id) {
            annotate_zabbix_event( $zabbix_event_id, $html_url );
        }
        else {
            die "Unable to determine zabbix event id";
        }

    }
    elsif ( $event_type eq 'incident.acknowledged' ) {
        if ($zabbix_event_id) {

            # Update Zabbix event acknowledgement
            acknowledge_zabbix_event( $zabbix_event_id, $event, $event_details );
        }
        else {
            die "Unable to determine zabbix event id";
        }
    }
    elsif ( $event_type eq 'incident.unacknowledged' ) {
        if ($zabbix_event_id) {
            unacknowledge_zabbix_event( $zabbix_event_id, $event, $event_details );
        }
        else {
            die "Unable to determine zabbix event id";
        }
    }
    elsif ( $event_type eq 'incident.annotated' ) {
        if ($zabbix_event_id) {
            my $who     = $event->{'agent'}{'summary'};
            my $content = $event->{'data'}{'content'};
            my $message = "$content -$who";

            annotate_zabbix_event( $zabbix_event_id, $message );
        }
        else {
            die "Unable to determine zabbix event id";
        }

    }
    elsif ( $event_type eq 'incident.resolved' ) {
        if ($zabbix_event_id) {
            close_zabbix_event( $zabbix_event_id, $event, $event_details );
        }
        else {
            die "Unable to determine zabbix event id";
        }
    }

    # PD event types we may want to handle:
    #    "incident.delegated",
    #    "incident.escalated",
    #    "incident.priority_updated",
    #    "incident.reassigned",
    #    "incident.reopened",
    #    "incident.resolved",
    #    "incident.responder.added",
    #    "incident.responder.replied",
    #    "incident.status_update_published",
}

sub get_event_details {
    my ($self_url) = @_;
    my $pdtoken = $config->get('pdtoken');

    my $pd_response = $ua->get( "${self_url}?include[]=body", 'Authorization' => "Token token=${pdtoken}", );
    $DEBUG >= 3 && warn Dumper($pd_response);
    if ( $pd_response->is_success ) {
        my $pd_json_content = $pd_response->content();
        my $content         = decode_json($pd_json_content);
        return $content->{'incident'};
    }
    else {
        die "Unable to fetch details from PagerDuty";
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
    $DEBUG && warn("Annotating Zabbix event $zabbix_event_id with message: $message");

    my %params = (
        eventids => $zabbix_event_id,
        action   => ZABBIX_ADD_MSG,     # bit-math
        message  => $message
    );
    $DEBUG > 2 && warn( "Annotate params: " . Dumper( \%params ) );
    update_zabbix_event(%params);
}

# Update Zabbix event w/acknowledgement
sub acknowledge_zabbix_event {
    my ( $zabbix_event_id, $event, $event_details ) = @_;
    my $who     = $event->{'agent'}{'summary'};
    my $message = "ACK'd in PD by $who";
    $DEBUG && warn("Acknowledging Zabbix event $zabbix_event_id");

    my %params = (
        eventids => $zabbix_event_id,
        action   => ZABBIX_ACK ^ ZABBIX_ADD_MSG,    # bit-math
        message  => $message
    );
    $DEBUG > 2 && warn( "Ack params: " . Dumper( \%params ) );
    update_zabbix_event(%params);

}

# Update Zabbix event w/unacknowledgement
sub unacknowledge_zabbix_event {
    my ( $zabbix_event_id, $event, $event_details ) = @_;
    my $who     = $event->{'agent'}{'summary'};
    my $message = "un-ACK'd in PD by $who";
    $DEBUG && warn("Unacknowledging Zabbix event $zabbix_event_id");

    my %params = (
        eventids => $zabbix_event_id,
        action   => ZABBIX_UNACK ^ ZABBIX_ADD_MSG,    # bit-math
        message  => $message
    );
    $DEBUG > 2 && warn( "Unack params: " . Dumper( \%params ) );
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
    my $message = "Resolved in PD by $who";
    $DEBUG && warn("Resolving Zabbix event $zabbix_event_id");

    my %params = (
        eventids => $zabbix_event_id,
        action   => ZABBIX_CLOSE ^ ZABBIX_ADD_MSG,    # bit-math
        message  => $message
    );
    $DEBUG > 2 && warn( "Ack params: " . Dumper( \%params ) );
    update_zabbix_event(%params);

    # TODO:
    # Implement your logic here to update the acknowledgement status of the Zabbix event
    # You need to make API calls to Zabbix to update the event
}

# Update Zabbix event:
sub update_zabbix_event {
    my %params = @_;

    $DEBUG && warn("Updating zabbix event\n");

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

    $DEBUG >= 2 && warn("Zabbix API payload: $json\n");

    my $zabbixresponse;
    my $zabbixretries = 0;
    until ( $zabbixresponse && $zabbixresponse->is_success ) {
        $zabbixresponse = $ua->post(
            $zabbixapiurl,
            'Content-Type'  => 'application/json-rpc',
            'Authorization' => "Bearer $zabbixtoken",
            Content         => $json,
        );
        $DEBUG && warn( Dumper($zabbixresponse) );

        if ( $zabbixretries >= 10 ) {
            warn Dumper($zabbixresponse);
            die "Couldn't talk to zabbix API.";
        }
        else {
            $zabbixretries++;
            sleep($zabbixretries);
        }
    }

    $DEBUG && warn( Dumper($zabbixresponse) );
}

