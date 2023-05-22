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
my @config_paths = (
    './.pagerduty2zabbix.conf',
    './pagerduty2zabbix.conf',
    '/etc/pagerduty2zabbix/pagerduty2zabbix.conf',
    '/etc/pagerduty2zabbix.conf',
);

# Create a new AppConfig object
my $config = AppConfig->new(
   debug => {
     DEFAULT => 1,
     ARGCOUNT => ARGCOUNT_ONE
   },
);

# Search for and load the first available configuration file
my $found_config = 0;
foreach my $config_path (@config_paths) {
    if (-e $config_path) {
        warn("Reading config $config_path\n");
        $config->file($config_path);
        $found_config = 1;
        last;
    }
}
if ($found_config) {
  $DEBUG = $config->param('debug');
} else {
  warn("No config found");
  $DEBUG = 1;
}

# TODO: find config
# TODO: Parse config
# with AppConfig?

my $cgi = CGI->new();

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
my $payload      = decode_json($json_payload);

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

    # Check if the PagerDuty event is an incident acknowledgement
    if ( $event->{'type'} eq 'incident.acknowledge' ) {
        my $incident_id     = $event->{'incident'}->{'id'};
        my $zabbix_event_id = get_zabbix_event_id($incident_id);

        if ($zabbix_event_id) {

            # Update Zabbix event acknowledgement
            acknowledge_zabbix_event($zabbix_event_id);
        }
    }
}

# Get the Zabbix event ID associated with a PagerDuty incident
sub get_zabbix_event_id {
    my ($pagerduty_incident_id) = @_;

    # TODO:
    # Implement your logic here to retrieve the Zabbix event ID based on the PagerDuty incident ID
    # You might need to make API calls to Zabbix to fetch the relevant information
    # Return undef if no matching event is found
}

# Update Zabbix event acknowledgement
sub acknowledge_zabbix_event {
    my ($zabbix_event_id) = @_;

    # TODO:
    # Implement your logic here to update the acknowledgement status of the Zabbix event
    # You need to make API calls to Zabbix to update the event
}
