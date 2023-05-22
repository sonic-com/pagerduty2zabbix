#!/usr/bin/perl
use warnings;
use strict;
use CGI;
use JSON;
use LWP::UserAgent;
use Data::Dumper;
use AppConfig;

# Define the configuration file search paths
my @config_paths = (
    './.pagerduty2zabbix.conf',                    './pagerduty2zabbix.conf',
    '/etc/pagerduty2zabbix/pagerduty2zabbix.conf', '/etc/pagerduty2zabbix.conf',
    "$ENV{HOME}/.pagerduty2zabbix.conf",
);

# Create a new AppConfig object
my $config = AppConfig->new();

$config->set_defaults( 'debug' => 1, );

# Search for and load the first available configuration file
my $found_config = 0;
foreach my $config_path (@config_paths) {
    if ( -e $config_path ) {
        $config->file($config_path);
        $found_config = 1;
        last;
    }
}

my $DEBUG = $config->param('debug');

# TODO: find config
# TODO: Parse config
# with AppConfig?

my $cgi = CGI->new();

# Always tell PD we got the message right away:
print $cgi->header();

if ($DEBUG) {
    print STDERR "Headers:\n";

    for my $header ( $cgi->http() ) {
        $DEBUG && print STDERR "$header: " . $cgi->http($header) . "\n";
    }
    print STDERR "POSTDATA:\n";
    print STDERR Dumper( $cgi->param('POSTDATA') );
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
    my $event = $payload->{'messages'}[0]->{'event'};

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
