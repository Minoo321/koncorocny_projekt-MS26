"""Registracny a prihlasovaci formular (Flask-WTF) s validaciou a CSRF ochranou."""
from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length


class RegisterForm(FlaskForm):
    username = StringField("Pouzivatelske meno",
                           validators=[DataRequired(), Length(min=3, max=25)])
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Heslo", validators=[DataRequired(), Length(min=6)])
    confirm = PasswordField("Heslo znova",
                            validators=[DataRequired(), EqualTo("password", message="Hesla sa nezhoduju.")])
    submit = SubmitField("Registrovat sa")


class LoginForm(FlaskForm):
    username = StringField("Pouzivatelske meno", validators=[DataRequired()])
    password = PasswordField("Heslo", validators=[DataRequired()])
    submit = SubmitField("Prihlasit sa")
