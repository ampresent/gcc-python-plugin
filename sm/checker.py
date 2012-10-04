#   Copyright 2012 David Malcolm <dmalcolm@redhat.com>
#   Copyright 2012 Red Hat, Inc.
#
#   This is free software: you can redistribute it and/or modify it
#   under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful, but
#   WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#   General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see
#   <http://www.gnu.org/licenses/>.

import gcc

from gccutils.graph import ReturnNode

class Checker:
    # Top-level object representing a .sm file
    def __init__(self, sms):
        self.sms = sms # list of Sm

    def __repr__(self):
        return 'Checker(%r)' % self.sms

    def to_dot(self, name):
        from sm.dot import checker_to_dot
        return checker_to_dot(self, name)

class Sm:
    def __init__(self, name, clauses):
        self.name = name
        self.clauses = clauses

    def __repr__(self):
        return ('Sm(name=%r, clauses=%r)'
                % (self.name, self.clauses))

    def iter_states(self):
        statenames = set()
        for sc in self.clauses:
            if isinstance(sc, StateClause):
                for statename in sc.statelist:
                    if statename not in statenames:
                        statenames.add(statename)
                        yield statename

class Clause:
    # top-level item within an sm
    pass

class Decl(Clause):
    # a matchable thing
    def __init__(self, has_state, name):
        self.has_state = has_state
        self.name = name

    def __hash__(self):
        return hash(self.name)

    @classmethod
    def make(cls, has_state, declkind, name):
        if declkind == 'any_pointer':
            return AnyPointer(has_state, name)
        elif declkind == 'any_expr':
            return AnyExpr(has_state, name)
        raise UnknownDeclkind(declkind)

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, self.name)

    def __eq__(self, other):
        if self.__class__ == other.__class__:
            if self.name == other.name:
                return True

    def matched_by(self, gccexpr):
        print(self)
        raise NotImplementedError()

class AnyPointer(Decl):
    def matched_by(self, gccexpr):
        return isinstance(gccexpr.type, gcc.PointerType)

class AnyExpr(Decl):
    def matched_by(self, gccexpr):
        return True

class StateClause(Clause):
    def __init__(self, statelist, patternrulelist):
        self.statelist = statelist
        self.patternrulelist = patternrulelist

    def __repr__(self):
        return 'StateClause(statelist=%r, patternrulelist=%r)' % (self.statelist, self.patternrulelist)

class PatternRule:
    def __init__(self, pattern, outcomes):
        self.pattern = pattern
        self.outcomes = outcomes

    def __repr__(self):
        return 'PatternRule(pattern=%r, outcomes=%r)' % (self.pattern, self.outcomes)

class Match:
    """
    A match of a pattern
    """
    def __init__(self, pattern):
        self.pattern = pattern
        self._dict = {}

    def __eq__(self, other):
        if isinstance(other, Match):
            return self.pattern == other.pattern and self._dict == other._dict

    def __hash__(self):
        return hash(self.pattern)

    def __repr__(self):
        return 'Match(%r, %r)' % (self.pattern, self._dict)

    def description(self, ctxt):
        return self.pattern.description(self, ctxt)

    def match_term(self, ctxt, gccexpr, smexpr):
        """
        Determine whether gccexpr matches smexpr;
        if it does, add it to this Match's dictionary
        """
        if 0:
            print('Match.match_term(self=%r, ctxt=%r, gccexpr=%r, smexpr=%r)'
                  % (self, ctxt, gccexpr, smexpr))
        if ctxt.compare(gccexpr, smexpr):
            if isinstance(smexpr, str):
                decl = ctxt.lookup_decl(smexpr)
                self._dict[decl] = gccexpr
            return True

    def describe(self, ctxt, smexpr):
        #print('Match.describe(self=%r, smexpr=%r)' % (self, smexpr))
        if isinstance(smexpr, str):
            decl = ctxt.lookup_decl(smexpr)
            return str(self._dict[decl])
        else:
            return str(smexpr)

    def describe_stateful_smexpr(self, ctxt):
        gccvar = self.get_stateful_gccvar(ctxt)
        return str(gccvar)

    def get_stateful_gccvar(self, ctxt):
        return self._dict[ctxt._stateful_decl]

    def iter_binding(self):
        for decl, gccexpr in self._dict.iteritems():
            yield (decl, gccexpr)

class Pattern:
    def iter_matches(self, stmt, edge, ctxt):
        print('self: %r' % self)
        raise NotImplementedError()

    def iter_expedge_matches(self, expedge, ctxt):
        return []

    def description(self, match, ctxt):
        print('self: %r' % self)
        raise NotImplementedError()

    def __hash__(self):
        return id(self)

class AssignmentFromLiteral(Pattern):
    def __init__(self, lhs, rhs):
        self.lhs = lhs
        self.rhs = rhs
    def __repr__(self):
        return 'AssignmentFromLiteral(lhs=%r, rhs=%r)' % (self.lhs, self.rhs)
    def __str__(self):
        return '%s = %s' % (self.lhs, self.rhs)
    def __eq__(self, other):
        if self.__class__ == other.__class__:
            if self.lhs == other.lhs:
                if self.rhs == other.rhs:
                    return True

    def iter_matches(self, stmt, edge, ctxt):
        if isinstance(stmt, gcc.GimpleAssign):
            m = Match(self)
            if m.match_term(ctxt, stmt.lhs, self.lhs):
                if m.match_term(ctxt, stmt.rhs[0], self.rhs):
                    yield m

    def description(self, match, ctxt):
        return ('%s assigned to %s'
                % (match.describe(ctxt, self.lhs), self.rhs))

class FunctionCall(Pattern):
    def __init__(self, fnname):
        self.fnname = fnname

    def __str__(self):
        return '%s(...)' % self.fnname

    def iter_matches(self, stmt, edge, ctxt):
        if isinstance(stmt, gcc.GimpleCall):
            if isinstance(stmt.fn, gcc.AddrExpr):
                if isinstance(stmt.fn.operand, gcc.FunctionDecl):
                    if stmt.fn.operand.name == self.fnname:
                        # We have a matching function name:
                        m = Match(self)
                        yield m

class ResultOfFnCall(FunctionCall):
    def __init__(self, lhs, func):
        FunctionCall.__init__(self, func)
        self.lhs = lhs
        self.func = func
    def __repr__(self):
        return 'ResultOfFnCall(lhs=%r, func=%r)' % (self.lhs, self.func)
    def __str__(self):
        return '%s = %s(...)' % (self.lhs, self.func)
    def __eq__(self, other):
        if self.__class__ == other.__class__:
            if self.lhs == other.lhs:
                if self.func == other.func:
                    return True

    def iter_matches(self, stmt, edge, ctxt):
        for m in FunctionCall.iter_matches(self, stmt, edge, ctxt):
            if m.match_term(ctxt, stmt.lhs, self.lhs):
                yield m

    def description(self, match, ctxt):
        return ('%s assigned to the result of %s()'
                % (match.describe(ctxt, self.lhs), self.func))


class ArgsOfFnCall(FunctionCall):
    def __init__(self, func, args):
        FunctionCall.__init__(self, func)
        self.func = func
        self.args = args
    def __repr__(self):
        return 'ArgsOfFnCall(func=%r, args=%r)' % (self.func, self.args)
    def __str__(self):
        return '%s(%s)' % (self.fnname,
                           ', '.join([str(arg)
                                      for arg in self.args]))
    def __eq__(self, other):
        if self.__class__ == other.__class__:
            if self.func == other.func:
                if self.args == other.args:
                    return True

    def iter_matches(self, stmt, edge, ctxt):
        for m in FunctionCall.iter_matches(self, stmt, edge, ctxt):
            def matches_args():
                for i, arg in enumerate(self.args):
                    if not m.match_term(ctxt, stmt.args[i], arg):
                        return False
                return True
            if matches_args():
                yield m

    def description(self, match, ctxt):
        return ('%s passed to %s()'
                % (match.get_stateful_gccvar(ctxt), self.func))

class Comparison(Pattern):
    def __init__(self, lhs, op, rhs):
        self.lhs = lhs
        self.op = op
        self.rhs = rhs
    def __repr__(self):
        return 'Comparison(%r, %r, %r)' % (self.lhs, self.op, self.rhs)
    def __str__(self):
        return '(%s %s %s)' % (self.lhs, self.op, self.rhs)
    def __eq__(self, other):
        if self.__class__ == other.__class__:
            if self.lhs == other.lhs:
                if self.op == other.op:
                    if self.rhs == other.rhs:
                        return True

    def iter_matches(self, stmt, edge, ctxt):
        if isinstance(stmt, gcc.GimpleCond):
            if 0:
                print('    %r %r %r %r %r' % (stmt.lhs, stmt.rhs, stmt.exprcode, stmt.true_label, stmt.false_label))
                print('edge: %r' % edge)
                print('edge.true_value: %r' % edge.true_value)
                print('edge.false_value: %r' % edge.false_value)

            # For now, specialcase:
            if self.op == '==':
                exprcode = gcc.EqExpr
                if stmt.exprcode == exprcode:
                    m = Match(self)
                    if m.match_term(ctxt, stmt.lhs, self.lhs):
                        if m.match_term(ctxt, stmt.rhs, self.rhs):
                            yield m
            elif self.op == '!=':
                exprcode = gcc.NeExpr
                if stmt.exprcode == exprcode:
                    m = Match(self)
                    if m.match_term(ctxt, stmt.lhs, self.lhs):
                        if m.match_term(ctxt, stmt.rhs, self.rhs):
                            yield m
            else:
                raise UnhandledConditional() # FIXME
            """
            if stmt.exprcode == gcc.EqExpr:
                op = '==' if edge.true_value else '!='
            elif stmt.exprcode == gcc.LtExpr:
                op = '<' if edge.true_value else '>='
            elif stmt.exprcode == gcc.LeExpr:
                op = '<=' if edge.true_value else '>'
            """

    def description(self, match, ctxt):
        return ('%s compared against %s'
                % (match.describe(ctxt, self.lhs),
                   match.describe(ctxt, self.rhs)))

class VarDereference(Pattern):
    def __init__(self, var):
        self.var = var
    def __repr__(self):
        return 'VarDereference(var=%r)' % self.var
    def __str__(self):
        return '*%s' % self.var
    def __eq__(self, other):
        if self.__class__ == other.__class__:
            if self.var == other.var:
                return True
    def iter_matches(self, stmt, edge, ctxt):
        def check_for_match(node, loc):
            if isinstance(node, gcc.MemRef):
                if ctxt.compare(node.operand, self.var):
                    return True
        # We don't care about the args during return-handling:
        if isinstance(edge.srcnode, ReturnNode):
            return
        t = stmt.walk_tree(check_for_match, stmt.loc)
        if t:
            m = Match(self)
            m.match_term(ctxt, t.operand, self.var)
            yield m

    def description(self, match, ctxt):
        return ('dereference of %s'
                % (match.describe(ctxt, self.var)))

class VarUsage(Pattern):
    def __init__(self, var):
        self.var = var
    def __repr__(self):
        return 'VarUsage(var=%r)' % self.var
    def __str__(self):
        return '%s' % self.var
    def __eq__(self, other):
        if self.__class__ == other.__class__:
            if self.var == other.var:
                return True
    def iter_matches(self, stmt, edge, ctxt):
        def check_for_match(node, loc):
            # print('check_for_match(%r, %r)' % (node, loc))
            if isinstance(node, (gcc.VarDecl, gcc.ParmDecl)):
                if ctxt.compare(node, self.var):
                    return True
        # We don't care about the args during return-handling:
        if isinstance(edge.srcnode, ReturnNode):
            return
        t = stmt.walk_tree(check_for_match, stmt.loc)
        if t:
            m = Match(self)
            m.match_term(ctxt, t, self.var)
            yield m

    def description(self, match, ctxt):
        return ('usage of %s' % match.describe(self.rhs))

class SpecialPattern(Pattern):
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return '$%s$' % self.name

    @classmethod
    def make(cls, name):
        if name == 'leaked':
            return LeakedPattern(name)

        class UnknownSpecialPattern(Exception):
            def __init__(self, name):
                self.name = name
        raise UnknownSpecialPattern(name)

class LeakedPattern(SpecialPattern):
    def iter_matches(self, stmt, edge, ctxt):
        return []

    def iter_expedge_matches(self, expedge, expgraph):
        if expedge.shapechange:
            for srcgccvar in expedge.shapechange.iter_leaks():
                m = Match(self)
                m._dict[expgraph.ctxt._stateful_decl]=srcgccvar
                yield m

    def description(self, match, ctxt):
        return 'leak of %s' % match.get_stateful_gccvar(ctxt)

    def __eq__(self, other):
        if self.__class__ == other.__class__:
            return True

class Outcome:
    pass

class TransitionTo(Outcome):
    def __init__(self, state):
        self.state = state
    def __repr__(self):
        return 'TransitionTo(state=%r)' % self.state
    def __eq__(self, other):
        if self.__class__ == other.__class__:
            if self.state == other.state:
                return True
    def apply(self, mctxt):
        # print('transition %s to %s' % (match.var, outcome.state))
        dststate = self.state
        dstshape, shapevars = mctxt.srcshape._copy()
        dstshape.set_state(mctxt.get_stateful_gccvar(), dststate)
        dstexpnode = mctxt.expgraph.lazily_add_node(mctxt.dstnode, dstshape)
        expedge = mctxt.expgraph.lazily_add_edge(mctxt.srcexpnode, dstexpnode,
                                                 mctxt.inneredge, mctxt.match, None)

class BooleanOutcome(Outcome):
    def __init__(self, guard, outcome):
        self.guard = guard
        self.outcome = outcome
    def __repr__(self):
        return 'BooleanOutcome(guard=%r, outcome=%r)' % (self.guard, self.outcome)
    def __eq__(self, other):
        if self.__class__ == other.__class__:
            if self.guard == other.guard:
                if self.outcome == other.outcome:
                    return True
    def apply(self, mctxt):
        if mctxt.inneredge.true_value and self.guard:
            self.outcome.apply(mctxt)
        if mctxt.inneredge.false_value and not self.guard:
            self.outcome.apply(mctxt)

class PythonOutcome(Outcome):
    def __init__(self, src):
        self.src = src
    def __repr__(self):
        return 'PythonOutcome(%r)' % (self.src, )
    def __eq__(self, other):
        if self.__class__ == other.__class__:
            if self.src == other.src:
                return True

    def apply(self, mctxt):
        ctxt = mctxt.expgraph.ctxt
        if 0:
            print('run(): %r' % self)
            print('  match: %r' % match)
            print('  expgraph: %r' % expgraph)
            print('  expnode: %r' % expnode)

        # Get at python code.
        expr = self.src

        # Create environment for execution of the code:
        def error(msg):
            ctxt.add_error(mctxt.expgraph, mctxt.srcexpnode, mctxt.match, msg)
        locals_ = {}
        globals_ = {'error' : error}

        # Bind the names for the matched Decls
        # For example, when:
        #      state decl any_pointer ptr;
        # has been matched by:
        #      void *q;
        # then we bind the string "ptr" to the gcc.VarDecl for q
        # (which has str() == 'q')
        for decl, value in mctxt.match.iter_binding():
            locals_[decl.name] = value
        if 0:
            print('  globals_: %r' % globals_)
            print('  locals_: %r' % locals_)
        # Now run the code:
        result = eval(expr, globals_, locals_)
