#!/usr/bin/perl
use warnings;
use strict;
use CGI;
use Data::Dumper;

my $DEBUG = 1;

my $cgi = CGI->new();

# Always tell PD we got the message right away:
print $cgi->header();

my $path = $cgi->url( -absolute => 1 );

$DEBUG && print STDERR "Path: $path\n";

my $pathcomponent = $path =~ m{.*/([^/])/pd2zabbix.cgi};

$DEBUG && print STDERR "Pathcomp: $pathcomponent\n";

$DEBUG && print STDERR "Headers?\n";
for my $header ( $cgi->http() ) {
    $DEBUG && print STDERR "$header: " . $cgi->http($header) . "\n";
}

$DEBUG && print STDERR "POSTDATA:\n";
$DEBUG && print STDERR Dumper( $cgi->param('POSTDATA') );

