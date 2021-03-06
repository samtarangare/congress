// Copyright (c) 2013 VMware, Inc. All rights reserved.
//
//    Licensed under the Apache License, Version 2.0 (the "License"); you may
//    not use this file except in compliance with the License. You may obtain
//    a copy of the License at
//
//         http://www.apache.org/licenses/LICENSE-2.0
//
//    Unless required by applicable law or agreed to in writing, software
//    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
//    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
//    License for the specific language governing permissions and limitations
//    under the License.
//

grammar Congress;

options {
    language=Python;
    output=AST;
    ASTLabelType=CommonTree;
}

tokens {
    PROG;
    COMMA=',';
    COLONMINUS=':-';
    LPAREN='(';
    RPAREN=')';
    // Structure
    THEORY;
    STRUCTURED_NAME;

    // Kinds of Formulas
    RULE;
    LITERAL;
    ATOM;
    NOT;
    AND;

    // Terms
    NAMED_PARAM;
    COLUMN_NAME;
    COLUMN_NUMBER;
    VARIABLE;
    STRING_OBJ;
    INTEGER_OBJ;
    FLOAT_OBJ;
    SYMBOL_OBJ;
}

prog
    : formula formula* EOF -> ^(THEORY formula+)
    | EOF
    ;

formula
    : bare_formula formula_terminator? -> bare_formula
    ;

formula_terminator
    : ';'
    | '.'
    ;

bare_formula
    : rule
    | atom
    ;

rule
    : literal_list COLONMINUS literal_list -> ^(RULE literal_list literal_list)
    ;

literal_list
    : literal (COMMA literal)* -> ^(AND literal+)
    ;

literal
    : atom      -> atom
    | NEGATION atom  -> ^(NOT atom)
    ;

NEGATION
    : 'not'
    | 'NOT'
    | '!'
    ;

atom
    : relation_constant (LPAREN parameter_list? RPAREN)? -> ^(ATOM relation_constant parameter_list?)
    ;

parameter_list
    : parameter (COMMA parameter)* -> parameter+
    ;

parameter
    : term -> term
    | column_ref EQUAL term -> ^(NAMED_PARAM column_ref term)
    ;

column_ref
    : ID   ->  ^(COLUMN_NAME ID)
    | INT  ->  ^(COLUMN_NUMBER INT)
    ;

term
    : object_constant
    | variable
    ;

object_constant
    : INT      -> ^(INTEGER_OBJ INT)
    | FLOAT    -> ^(FLOAT_OBJ FLOAT)
    | STRING   -> ^(STRING_OBJ STRING)
    ;

variable
    : ID -> ^(VARIABLE ID)
    ;

relation_constant
    : ID (':' ID)* SIGN? -> ^(STRUCTURED_NAME ID+ SIGN?)
    ;

EQUAL
    :  '='
    ;

SIGN
    :  '+' | '-'
    ;

ID  :   ('a'..'z'|'A'..'Z'|'_'|'.') ('a'..'z'|'A'..'Z'|'0'..'9'|'_'|'.')*
    ;

INT :   '0'..'9'+
    ;

FLOAT
    :   ('0'..'9')+ '.' ('0'..'9')* EXPONENT?
    |   '.' ('0'..'9')+ EXPONENT?
    |   ('0'..'9')+ EXPONENT
    ;

COMMENT
    :   '//' ~('\n'|'\r')* '\r'? '\n' {$channel=HIDDEN;}
    |   '/*' ( options {greedy=false;} : . )* '*/' {$channel=HIDDEN;}
    ;

WS  :   ( ' '
        | '\t'
        | '\r'
        | '\n'
        ) {$channel=HIDDEN;}
    ;

// Characters in string are either
//    (i) any character except ", carriage-return, linefeed, backslash
//    (ii) an escape sequence like \t, \n, \r
//    (iii) or a universal character name like \u10af
// Order of the above 3 in the following rule is important.
STRING
    : '"' (~('"' | '\r' | '\n' | '\\')
           | ESC_SEQ )*
      '"'
    ;

// Escape sequences
// Simple escape sequences like \n, \t, \\ are taken from Stroustrup.
// Octal escape sequences are either 1, 2, or 3 octal digits exactly.
// Hexadecimal escape sequences begin with \x and continue until non-hex found.
// No handling of tri-graph sequences.



CHAR:  '\'' ( ESC_SEQ | ~('\''|'\\') ) '\''
    ;

fragment
EXPONENT : ('e'|'E') ('+'|'-')? ('0'..'9')+ ;

fragment
HEX_DIGIT : ('0'..'9'|'a'..'f'|'A'..'F') ;

fragment
ESC_SEQ
    :   '\\' ('b'|'t'|'n'|'f'|'r'|'"'|'\''|'\\')
    |   UNICODE_ESC
    |   OCTAL_ESC
    ;

fragment
OCTAL_ESC
    :   '\\' ('0'..'3') ('0'..'7') ('0'..'7')
    |   '\\' ('0'..'7') ('0'..'7')
    |   '\\' ('0'..'7')
    ;

fragment
UNICODE_ESC
    :   '\\' 'u' HEX_DIGIT HEX_DIGIT HEX_DIGIT HEX_DIGIT
    ;
