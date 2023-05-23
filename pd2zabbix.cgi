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
use AppConfig qw/:expand :argcount/;

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

# TODO: find config
# TODO: Parse config
# with AppConfig?

our $cgi = CGI->new();

our $ua = LWP::UserAgent->new( agent => 'pagerduty2zabbix (https://github.com/sonic-com/pagerduty2zabbix)' );

# Always tell PD we got the message right away:
print $cgi->header();

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
# TODO: Also need to check that this event is for a zabbix install we're configured for...
sub handle_pagerduty_webhook {
    my ($payload) = @_;

    my $event = $payload->{'event'};
    $DEBUG >= 3 && warn( "event: " . Dumper($event) . "\n" );
    my $self_url = $event->{'data'}{'self'};
    $DEBUG && warn("self_url: $self_url\n");
    my $html_url = $event->{'data'}{'html_url'};
    $DEBUG && warn("html_url: $html_url\n");

    my $event_details   = get_event_details($self_url);
    my $zabbix_event_id = get_zabbix_event_id($event_details);

    my $event_type = $event->{'event_type'};
    $DEBUG && warn("event_type: $event_type\n");

    # Check if the PagerDuty event is an incident acknowledgement
    if ( $event_type eq 'incident.acknowledged' ) {
        if ($zabbix_event_id) {

            # Update Zabbix event acknowledgement
            acknowledge_zabbix_event($zabbix_event_id);
        }
        else {
            die "Unable to determine zabbix event id";
        }
    }
}

sub get_event_details {
    my ($self_url) = @_;
    my $pdtoken = $config->get('pdtoken');

    # curl --header "Authorization: Token token=u+VL5q2Kv2zgLJDfgmRg" \
    #    "https://api.pagerduty.com/incidents/Q25OHYUWS2W4Z6?include[]=body"

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

    # incident->body->details->dedup_key
}

# Update Zabbix event acknowledgement
sub acknowledge_zabbix_event {
    my ($zabbix_event_id) = @_;
    $DEBUG && warn("Acknowledging Zabbix event $zabbix_event_id");

    # TODO:
    # Implement your logic here to update the acknowledgement status of the Zabbix event
    # You need to make API calls to Zabbix to update the event
}
